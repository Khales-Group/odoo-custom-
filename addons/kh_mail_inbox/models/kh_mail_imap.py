"""Reading a mailbox over IMAP, read-only (no Odoo imports: testable alone).

The folder is opened with EXAMINE and every fetch uses BODY.PEEK, so the
server never marks a message as read, and nothing is ever moved, deleted
or sent. A message is read in two small steps: its headers, flags and
BODYSTRUCTURE (which names the attachments without downloading them),
then the beginning of its text part only. An attachment is fetched on
its own, when someone opens it.
"""
import base64
import binascii
import email.policy
import imaplib
import quopri
import re
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.parser import BytesHeaderParser
from email.utils import collapse_rfc2231_value, decode_rfc2231, getaddresses, parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import unquote

HEADER_FIELDS = (
    "FROM", "TO", "CC", "SUBJECT", "DATE", "MESSAGE-ID", "IN-REPLY-TO",
    "LIST-UNSUBSCRIBE", "PRECEDENCE", "AUTO-SUBMITTED",
)
META_ITEMS = "(UID FLAGS INTERNALDATE RFC822.SIZE BODYSTRUCTURE BODY.PEEK[HEADER.FIELDS (%s)])" % " ".join(HEADER_FIELDS)
TEXT_LIMIT = 65536  # bytes of a text part read per message
FETCH_CHUNK = 50
NOREPLY = re.compile(r"no-?reply|do-?not-?reply|mailer-daemon|postmaster|notifications?@|bounce", re.I)
MESSAGE_ID = re.compile(r"<([^<>\s]+)>")


# ----------------------------------------------------------------------
# IMAP response parsing
# ----------------------------------------------------------------------

def _raw(data):
    """imaplib's response list -> the bytes as sent (a literal follows its {n})."""
    raw = b""
    for part in data or ():
        if part is None:
            continue
        if isinstance(part, tuple):
            raw += part[0] + part[1]
        else:
            raw += part
    return raw


class _Reader:
    def __init__(self, raw):
        self.raw = raw
        self.pos = 0

    def skip_space(self):
        while self.pos < len(self.raw) and self.raw[self.pos] in b" \r\n":
            self.pos += 1

    def at_end(self):
        self.skip_space()
        return self.pos >= len(self.raw)

    def value(self):
        self.skip_space()
        char = self.raw[self.pos:self.pos + 1]
        if char == b"(":
            self.pos += 1
            items = []
            while True:
                self.skip_space()
                if self.raw[self.pos:self.pos + 1] == b")":
                    self.pos += 1
                    return items
                if self.pos >= len(self.raw):
                    return items
                items.append(self.value())
        if char == b'"':
            self.pos += 1
            out = bytearray()
            while self.pos < len(self.raw):
                c = self.raw[self.pos]
                if c == 0x5C:  # backslash
                    out.append(self.raw[self.pos + 1])
                    self.pos += 2
                    continue
                self.pos += 1
                if c == 0x22:
                    break
                out.append(c)
            return bytes(out)
        if char == b"{":
            # imaplib drops the CRLF after {size}: the literal starts right
            # after it (and may itself start with a blank line).
            end = self.raw.index(b"}", self.pos)
            size = int(self.raw[self.pos + 1:end])
            start = end + 1
            self.pos = start + size
            return self.raw[start:start + size]
        return self.atom()

    def atom(self):
        start, depth = self.pos, 0
        while self.pos < len(self.raw):
            c = self.raw[self.pos:self.pos + 1]
            if c in b"[<":
                depth += 1
            elif c in b"]>":
                depth -= 1
            elif depth <= 0 and c in b" ()\r\n":
                break
            self.pos += 1
        word = self.raw[start:self.pos]
        return None if word.upper() == b"NIL" else word


def parse_fetch(data):
    """A FETCH response -> [{item name: value}], item names upper-cased,
    a partial fetch's <origin> dropped (BODY[1]<0> -> BODY[1])."""
    reader = _Reader(_raw(data))
    messages = []
    while not reader.at_end():
        reader.atom()  # the message sequence number
        if reader.at_end():
            break
        items = reader.value()
        if not isinstance(items, list):
            continue
        entry = {}
        for name, value in zip(items[::2], items[1::2]):
            if isinstance(name, bytes):
                key = re.sub(rb"<\d+>$", b"", name).decode("ascii", "replace").upper()
                entry[key] = value
        messages.append(entry)
    return messages


def parse_uids(data):
    """A SEARCH response -> sorted UIDs."""
    words = b" ".join(part for part in data if isinstance(part, bytes)).split()
    return sorted({int(word) for word in words if word.isdigit()})


# ----------------------------------------------------------------------
# BODYSTRUCTURE
# ----------------------------------------------------------------------

def _text(value):
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def _params(value):
    if not isinstance(value, list):
        return {}
    return {_text(k).lower(): _text(v) for k, v in zip(value[::2], value[1::2])}


def decode_words(value):
    """RFC 2047 encoded words -> text."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # noqa: BLE001 - a broken header is shown as it is
        return value


def _filename(params, disposition_params):
    for source in (disposition_params, params):
        for key in ("filename*", "name*"):
            if source.get(key):
                value = source[key]
                if "''" in value:  # charset''percent-encoded (RFC 2231)
                    charset, _sep, encoded = value.partition("''")
                    try:
                        return unquote(encoded, encoding=charset or "utf-8", errors="replace")
                    except LookupError:
                        return unquote(encoded)
                return collapse_rfc2231_value(decode_rfc2231(value))
        for key in ("filename", "name"):
            if source.get(key):
                return decode_words(source[key])
    return ""


def _disposition(part):
    """(kind, params) of a single part, from its extension data."""
    for value in part[7:]:
        if (isinstance(value, list) and len(value) == 2 and isinstance(value[0], bytes)
                and (value[1] is None or isinstance(value[1], list))):
            return _text(value[0]).lower(), _params(value[1])
    return "", {}


def walk_structure(structure):
    """BODYSTRUCTURE -> (text part or None, [attachments]).

    A part: {"path": "1.2", "type": "text/plain", "charset", "encoding",
    "size", "name"}. The text part is the first plain text one that isn't
    an attachment (else the first HTML one)."""
    plain, html, attachments = [], [], []

    def visit(node, path):
        if not isinstance(node, list) or not node:
            return
        if isinstance(node[0], list):  # multipart: children, then the subtype
            index = 0
            for child in node:
                if not isinstance(child, list):
                    break
                index += 1
                visit(child, f"{path}.{index}" if path else str(index))
            return
        main, sub = _text(node[0]).lower(), _text(node[1]).lower() if len(node) > 1 else ""
        params = _params(node[2]) if len(node) > 2 else {}
        kind, disposition_params = _disposition(node)
        part = {
            "path": path or "1",
            "type": f"{main}/{sub}",
            "charset": params.get("charset", ""),
            "encoding": _text(node[5]).lower() if len(node) > 5 else "",
            "size": int(node[6]) if len(node) > 6 and isinstance(node[6], bytes) and node[6].isdigit() else 0,
            "name": _filename(params, disposition_params),
        }
        if main == "text" and kind != "attachment" and not (part["name"] and kind != "inline"):
            (plain if sub == "plain" else html if sub == "html" else []).append(part)
        elif main == "message" and sub == "rfc822":
            part["name"] = part["name"] or "forwarded-message.eml"
            attachments.append(part)
        elif kind == "attachment" or (part["name"] and kind != "inline"):
            attachments.append(part)

    visit(structure, "")
    text = plain[0] if plain else (html[0] if html else None)
    return text, attachments


# ----------------------------------------------------------------------
# Decoding
# ----------------------------------------------------------------------

def decode_transfer(raw, encoding):
    encoding = (encoding or "").lower()
    if encoding == "base64":
        compact = re.sub(rb"[^A-Za-z0-9+/=]", b"", raw or b"")
        compact = compact[:len(compact) - len(compact) % 4]
        try:
            return base64.b64decode(compact)
        except (binascii.Error, ValueError):
            return b""
    if encoding == "quoted-printable":
        return quopri.decodestring(raw or b"")
    return raw or b""


def to_unicode(raw, charset):
    for name in (charset, "utf-8", "cp1256", "latin-1"):
        if not name:
            continue
        try:
            return raw.decode(name)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


class _HtmlText(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head", "title"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head", "title"):
            self.skip = max(self.skip - 1, 0)
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(html):
    parser = _HtmlText()
    try:
        parser.feed(html)
        parser.close()
        text = "".join(parser.out)
    except Exception:  # noqa: BLE001 - very broken HTML: drop the tags roughly
        text = unescape(re.sub(r"<[^>]+>", " ", html))
    return tidy_text(text)


def tidy_text(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    lines = [re.sub(r"[ \t​‌‎‏]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _utc(value):
    if value.tzinfo:
        value = value.astimezone(timezone.utc)
    return value.replace(tzinfo=None)


def parse_internaldate(value):
    try:
        return _utc(datetime.strptime(_text(value), "%d-%b-%Y %H:%M:%S %z"))
    except ValueError:
        return None


def parse_headers(raw):
    """The fetched header fields -> plain values (dates as naive UTC)."""
    headers = BytesHeaderParser(policy=email.policy.compat32).parsebytes(raw or b"")

    def get(name):
        return decode_words(str(headers.get(name) or "")).strip()

    def addresses(name):
        found = getaddresses([decode_words(str(v)) for v in headers.get_all(name) or []])
        return [(display.strip(), address.strip().lower()) for display, address in found if address or display]

    sent = None
    if headers.get("Date"):
        try:
            sent = _utc(parsedate_to_datetime(str(headers["Date"])))
        except (TypeError, ValueError, IndexError):
            sent = None
    senders = addresses("From")
    precedence = get("Precedence").lower()
    auto = get("Auto-Submitted").lower()
    return {
        "subject": get("Subject"),
        "from_name": senders[0][0] if senders else "",
        "from_email": senders[0][1] if senders else "",
        "to": ", ".join(f"{n} <{a}>" if n and a else (a or n) for n, a in addresses("To")),
        "cc": ", ".join(f"{n} <{a}>" if n and a else (a or n) for n, a in addresses("Cc")),
        "date": sent,
        "message_id": get("Message-ID").strip("<> "),
        "in_reply_to": get("In-Reply-To").strip("<> "),
        "bulk": bool(
            headers.get("List-Unsubscribe") or precedence in ("bulk", "list", "junk")
            or (auto and auto != "no")
            or NOREPLY.search(senders[0][1] if senders else "")
        ),
    }


def read_message(meta, text_raw=None):
    """One message's FETCH items (and its text part's bytes, when read) ->
    the values to keep."""
    structure = meta.get("BODYSTRUCTURE")
    text_part, attachments = walk_structure(structure) if structure else (None, [])
    header_raw = next((v for k, v in meta.items() if k.startswith("BODY[HEADER")), b"")
    values = parse_headers(header_raw if isinstance(header_raw, bytes) else b"")
    flags = {_text(f).lower() for f in meta.get("FLAGS") or [] if f}
    body, truncated = "", False
    if text_part and text_raw is not None:
        truncated = text_part["size"] > TEXT_LIMIT or len(text_raw) >= TEXT_LIMIT
        text = to_unicode(decode_transfer(text_raw, text_part["encoding"]), text_part["charset"])
        body = html_to_text(text) if text_part["type"] == "text/html" else tidy_text(text)
    values.update({
        "uid": int(meta.get("UID") or 0),
        "date": values["date"] or parse_internaldate(meta.get("INTERNALDATE")),
        "size": int(meta.get("RFC822.SIZE") or 0),
        "seen": "\\seen" in flags,
        "answered": "\\answered" in flags,
        "flagged": "\\flagged" in flags,
        "body": body,
        "truncated": truncated,
        "attachments": [
            {"path": a["path"], "name": a["name"] or "attachment", "mimetype": a["type"],
             "size": a["size"], "encoding": a["encoding"]}
            for a in attachments
        ],
    })
    return values


# ----------------------------------------------------------------------
# The connection
# ----------------------------------------------------------------------

class ImapReader:
    """A read-only IMAP session: with ImapReader(...) as reader: ..."""

    def __init__(self, host, port, login, password, timeout=60):
        self.host, self.port, self.login, self.password, self.timeout = host, port, login, password, timeout
        self.imap = None

    def __enter__(self):
        self.imap = imaplib.IMAP4_SSL(self.host, int(self.port or 993), timeout=self.timeout)
        self.imap.login(self.login, self.password)
        return self

    def __exit__(self, *exc):
        try:
            self.imap.logout()
        except Exception:  # noqa: BLE001 - already gone
            pass

    def _ok(self, typ, data, what):
        if typ != "OK":
            raise imaplib.IMAP4.error(f"{what}: {_text(data[0]) if data else typ}")
        return data

    def examine(self, folder):
        """Opens the folder read-only -> (uidvalidity, number of messages)."""
        data = self._ok(*self.imap.select(f'"{folder}"', readonly=True), f"open {folder}")
        exists = int(data[0] or 0)
        validity = self.imap.response("UIDVALIDITY")[1]
        return int(validity[0]) if validity and validity[0] else 0, exists

    def search(self, criteria):
        return parse_uids(self._ok(*self.imap.uid("SEARCH", None, criteria), "search"))

    def _fetch(self, uids, items):
        out = []
        for start in range(0, len(uids), FETCH_CHUNK):
            chunk = ",".join(str(uid) for uid in uids[start:start + FETCH_CHUNK])
            out += parse_fetch(self._ok(*self.imap.uid("FETCH", chunk, items), "fetch"))
        return out

    def messages(self, uids):
        """[values] for these UIDs (headers, flags, attachments' names, text)."""
        metas = [m for m in self._fetch(sorted(uids), META_ITEMS) if m.get("UID")]
        by_path = {}
        for meta in metas:
            text_part, _attachments = walk_structure(meta["BODYSTRUCTURE"]) if meta.get("BODYSTRUCTURE") else (None, [])
            if text_part:
                by_path.setdefault(text_part["path"], []).append(int(meta["UID"]))
        texts = {}
        for path, path_uids in by_path.items():
            section = f"BODY[{path}]"
            for entry in self._fetch(path_uids, f"(UID BODY.PEEK[{path}]<0.{TEXT_LIMIT}>)"):
                if entry.get("UID") and isinstance(entry.get(section), bytes):
                    texts[int(entry["UID"])] = entry[section]
        return [read_message(meta, texts.get(int(meta["UID"]), b"" if meta.get("BODYSTRUCTURE") else None))
                for meta in metas]

    def flags(self, first_uid):
        """{uid: (seen, answered, flagged)} for UIDs from first_uid on."""
        out = {}
        for entry in parse_fetch(self._ok(*self.imap.uid("FETCH", f"{first_uid}:*", "(UID FLAGS)"), "flags")):
            if entry.get("UID"):
                flags = {_text(f).lower() for f in entry.get("FLAGS") or [] if f}
                out[int(entry["UID"])] = ("\\seen" in flags, "\\answered" in flags, "\\flagged" in flags)
        return out

    def reply_refs(self, uids):
        """The Message-IDs that these (sent) messages answer."""
        refs = set()
        for entry in self._fetch(sorted(uids), "(UID BODY.PEEK[HEADER.FIELDS (IN-REPLY-TO REFERENCES)])"):
            raw = next((v for k, v in entry.items() if k.startswith("BODY[HEADER")), b"")
            if isinstance(raw, bytes):
                refs.update(ref.strip() for ref in MESSAGE_ID.findall(raw.decode("utf-8", "replace")))
        return refs

    def part(self, uid, path, encoding):
        """One part's decoded bytes (an attachment, opened by someone)."""
        section = f"BODY[{path}]"
        for entry in parse_fetch(self._ok(*self.imap.uid("FETCH", str(uid), f"(UID BODY.PEEK[{path}])"), "fetch part")):
            if isinstance(entry.get(section), bytes):
                return decode_transfer(entry[section], encoding)
        return None
