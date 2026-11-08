from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import content_disposition, request


class KhMailInboxController(http.Controller):
    @http.route("/kh_mail_inbox/attachment/<int:message_id>/<int:index>", type="http", auth="user")
    def attachment(self, message_id, index, **kwargs):
        """An attachment, read from the mailbox when opened (not kept in Odoo)."""
        message = request.env["kh.mail.message"].browse(message_id).exists()
        try:
            if not message:
                raise UserError(request.env._("This message doesn't exist."))
            message._kh_check_manager()
            message.check_access("read")
            content, name, mimetype = message._kh_attachment(index)
        except AccessError:
            raise request.not_found()
        except UserError as error:
            return request.make_response(str(error), headers=[("Content-Type", "text/plain; charset=utf-8")], status=404)
        disposition = "attachment" if kwargs.get("download") else "inline"
        return request.make_response(content, headers=[
            ("Content-Type", mimetype),
            ("Content-Disposition", content_disposition(name, disposition)),
            ("Cache-Control", "private, max-age=600"),
            ("X-Content-Type-Options", "nosniff"),
        ])
