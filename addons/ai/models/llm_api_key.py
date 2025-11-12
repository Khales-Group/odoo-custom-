from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, AccessError
import base64
import logging
import requests
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import os

_logger = logging.getLogger(__name__)


class LLMApiKey(models.Model):
    """Model for secure storage of LLM API keys."""
    
    _name = 'llm.api.key'
    _description = 'LLM API Key'
    _order = 'name'
    
    name = fields.Char(
        string='Key Name',
        required=True,
        help='Human-readable name for this API key (e.g., "OpenAI Production Key")'
    )
    
    provider_type = fields.Selection([
        ('openai', 'OpenAI'),
        ('gemini', 'Google Gemini'),
        ('claude', 'Anthropic Claude'),
        ('other', 'Other'),
    ], string='Provider Type', required=True, help='Type of LLM provider this key is for')
    
    encrypted_key = fields.Binary(
        string='Encrypted API Key',
        attachment=True,
        help='Encrypted API key stored securely'
    )
    
    encrypted_key_filename = fields.Char(
        string='Encrypted Key Filename',
        help='Filename for the encrypted key attachment'
    )
    
    is_active = fields.Boolean(
        string='Active',
        default=True,
        help='Enable or disable this API key'
    )
    
    notes = fields.Text(
        string='Notes',
        help='Additional notes about this API key'
    )
    
    # Security fields
    created_by = fields.Many2one(
        'res.users',
        string='Created By',
        default=lambda self: self.env.user,
        readonly=True,
        help='User who created this API key'
    )
    
    created_date = fields.Datetime(
        string='Created Date',
        default=fields.Datetime.now,
        readonly=True,
        help='Date when this API key was created'
    )
    
    last_used = fields.Datetime(
        string='Last Used',
        readonly=True,
        help='Date when this API key was last used'
    )
    
    usage_count = fields.Integer(
        string='Usage Count',
        default=0,
        readonly=True,
        help='Number of times this API key has been used'
    )
    
    # Constraints
    _sql_constraints = [
        ('unique_name', 'unique(name)', 'API key name must be unique!'),
    ]
    
    def _get_encryption_key(self):
        """Get or create the encryption key for API keys."""
        # Try to get from system parameter first
        encryption_key = self.env['ir.config_parameter'].sudo().get_param(
            'ai_automation_base.encryption_key'
        )
        
        if not encryption_key:
            # Generate a new encryption key
            salt = os.urandom(16)
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            # Use a combination of system info as password
            password = f"{self.env.cr.dbname}_{self.env.uid}".encode()
            encryption_key = base64.urlsafe_b64encode(kdf.derive(password))
            
            # Store the encryption key
            self.env['ir.config_parameter'].sudo().set_param(
                'ai_automation_base.encryption_key',
                encryption_key.decode()
            )
        else:
            encryption_key = encryption_key.encode()
        
        return encryption_key
    
    def _encrypt_api_key(self, api_key):
        """Encrypt the API key."""
        if not api_key:
            return None
        
        try:
            encryption_key = self._get_encryption_key()
            fernet = Fernet(encryption_key)
            encrypted_data = fernet.encrypt(api_key.encode())
            return encrypted_data
        except Exception as e:
            _logger.error(f"Failed to encrypt API key: {str(e)}")
            raise ValidationError(_('Failed to encrypt API key: %s') % str(e))
    
    def _decrypt_api_key(self, encrypted_data):
        """Decrypt the API key."""
        if not encrypted_data:
            return None
        
        try:
            encryption_key = self._get_encryption_key()
            fernet = Fernet(encryption_key)
            decrypted_data = fernet.decrypt(encrypted_data)
            return decrypted_data.decode()
        except Exception as e:
            _logger.error(f"Failed to decrypt API key: {str(e)}")
            raise ValidationError(_('Failed to decrypt API key: %s') % str(e))
    
    @api.model
    def create(self, vals):
        """Override create to handle API key encryption."""
        if 'api_key' in vals:
            # Encrypt the API key before storing
            encrypted_key = self._encrypt_api_key(vals['api_key'])
            vals['encrypted_key'] = encrypted_key
            vals['encrypted_key_filename'] = f"api_key_{vals.get('name', 'unknown')}.enc"
            del vals['api_key']  # Remove the plain text key
        
        return super().create(vals)
    
    def write(self, vals):
        """Override write to handle API key encryption."""
        if 'api_key' in vals:
            # Encrypt the API key before storing
            encrypted_key = self._encrypt_api_key(vals['api_key'])
            vals['encrypted_key'] = encrypted_key
            vals['encrypted_key_filename'] = f"api_key_{vals.get('name', self.name)}.enc"
            del vals['api_key']  # Remove the plain text key
        
        return super().write(vals)
    
    def get_decrypted_key(self):
        """Get the decrypted API key."""
        self.ensure_one()
        
        # Check access rights
        if not self.env.user.has_group('ai_automation_base.group_ai_admin'):
            raise AccessError(_('You do not have permission to access API keys.'))
        
        # Update usage statistics
        self.write({
            'last_used': fields.Datetime.now(),
            'usage_count': self.usage_count + 1,
        })
        
        return self._decrypt_api_key(self.encrypted_key)
    
    def set_api_key(self, api_key):
        """Set a new API key (encrypted)."""
        self.ensure_one()
        
        encrypted_key = self._encrypt_api_key(api_key)
        self.write({
            'encrypted_key': encrypted_key,
            'encrypted_key_filename': f"api_key_{self.name}.enc",
        })
    
    def test_api_key(self):
        """Test if the API key is valid."""
        self.ensure_one()
        
        try:
            api_key = self.get_decrypted_key()
            if not api_key:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('API Key Test'),
                        'message': _('No API key found.'),
                        'type': 'warning',
                    }
                }
            
            # Test the key based on provider type
            if self.provider_type == 'openai':
                return self._test_openai_key(api_key)
            elif self.provider_type == 'gemini':
                return self._test_gemini_key(api_key)
            elif self.provider_type == 'claude':
                return self._test_claude_key(api_key)
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('API Key Test'),
                        'message': _('Provider type not supported for testing.'),
                        'type': 'warning',
                    }
                }
                
        except Exception as e:
            _logger.error(f"API key test failed: {str(e)}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('API Key Test Failed'),
                    'message': _('Failed to test API key: %s') % str(e),
                    'type': 'danger',
                }
            }
    
    def _test_openai_key(self, api_key):
        """Test OpenAI API key."""
        import requests
        
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }
        
        response = requests.get(
            'https://api.openai.com/v1/models',
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('API Key Test'),
                    'message': _('OpenAI API key is valid.'),
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('API Key Test Failed'),
                    'message': _('OpenAI API key is invalid or expired.'),
                    'type': 'danger',
                }
            }
    
    def _test_gemini_key(self, api_key):
        """Test Google Gemini API key."""
        import requests
        
        url = f'https://generativelanguage.googleapis.com/v1beta/models?key={api_key}'
        
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('API Key Test'),
                    'message': _('Google Gemini API key is valid.'),
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('API Key Test Failed'),
                    'message': _('Google Gemini API key is invalid or expired.'),
                    'type': 'danger',
                }
            }
    
    def _test_claude_key(self, api_key):
        """Test Anthropic Claude API key."""
        import requests
        
        headers = {
            'x-api-key': api_key,
            'Content-Type': 'application/json',
            'anthropic-version': '2023-06-01',
        }
        
        response = requests.get(
            'https://api.anthropic.com/v1/models',
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('API Key Test'),
                    'message': _('Anthropic Claude API key is valid.'),
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('API Key Test Failed'),
                    'message': _('Anthropic Claude API key is invalid or expired.'),
                    'type': 'danger',
                }
            }
    
    def name_get(self):
        """Custom name display for API keys."""
        result = []
        for record in self:
            name = f"{record.name} ({record.provider_type})"
            if not record.is_active:
                name += " [Inactive]"
            result.append((record.id, name))
        return result 