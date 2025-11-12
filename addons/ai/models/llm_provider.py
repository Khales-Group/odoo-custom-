from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import json
import logging

_logger = logging.getLogger(__name__)


class LLMProvider(models.Model):
    """Model for managing LLM service providers configuration."""
    
    _name = 'llm.provider'
    _description = 'LLM Service Provider'
    _order = 'name'
    
    name = fields.Char(
        string='Provider Name',
        required=True,
        help='Human-readable name for the LLM provider (e.g., "OpenAI", "Google Gemini")'
    )
    
    code = fields.Char(
        string='Provider Code',
        required=True,
        help='Unique programmatic identifier for the provider (e.g., "openai", "gemini")'
    )
    
    api_base_url = fields.Char(
        string='API Base URL',
        required=True,
        help='Base URL for the LLM API endpoint'
    )
    
    default_model_id = fields.Many2one(
        'llm.provider.model',
        string='Default Model',
        required=True,
        help='Default LLM model to use for this provider'
    )
    
    api_key_id = fields.Many2one(
        'llm.api.key',
        string='API Key',
        required=True,
        help='Secure reference to the stored API key'
    )
    
    is_active = fields.Boolean(
        string='Active',
        default=True,
        help='Enable or disable this provider'
    )
    
    provider_specific_config = fields.Text(
        string='Provider-Specific Configuration',
        help='JSON configuration for provider-specific settings (e.g., organization_id for OpenAI)'
    )
    
    notes = fields.Text(
        string='Notes',
        help='Additional notes or internal documentation'
    )
    
    # Related fields for monitoring
    llm_request_log_ids = fields.One2many(
        'llm.request.log',
        'provider_id',
        string='Request Logs',
        help='Logs of API requests made to this provider'
    )
    
    # Computed fields for monitoring
    last_request_date = fields.Datetime(
        string='Last Request',
        compute='_compute_last_request',
        store=True,
        help='Date of the last successful API request'
    )
    
    total_requests = fields.Integer(
        string='Total Requests',
        compute='_compute_total_requests',
        store=True,
        help='Total number of API requests made'
    )
    
    success_rate = fields.Float(
        string='Success Rate (%)',
        compute='_compute_success_rate',
        store=True,
        help='Percentage of successful API requests'
    )
    
    # Constraints
    _sql_constraints = [
        ('unique_code', 'unique(code)', 'Provider code must be unique!'),
    ]
    
    @api.constrains('provider_specific_config')
    def _check_provider_specific_config(self):
        """Validate that provider_specific_config is valid JSON."""
        for record in self:
            if record.provider_specific_config:
                try:
                    json.loads(record.provider_specific_config)
                except json.JSONDecodeError:
                    raise ValidationError(_('Provider-specific configuration must be valid JSON.'))
    
    @api.constrains('api_base_url')
    def _check_api_base_url(self):
        """Validate API base URL format."""
        for record in self:
            if record.api_base_url:
                if not record.api_base_url.startswith(('http://', 'https://')):
                    raise ValidationError(_('API Base URL must start with http:// or https://'))
    
    @api.depends('llm_request_log_ids')
    def _compute_last_request(self):
        """Compute the date of the last successful API request."""
        for record in self:
            last_log = self.env['llm.request.log'].search([
                ('provider_id', '=', record.id),
                ('status', '=', 'success')
            ], order='create_date desc', limit=1)
            record.last_request_date = last_log.create_date if last_log else False
    
    @api.depends('llm_request_log_ids')
    def _compute_total_requests(self):
        """Compute total number of API requests."""
        for record in self:
            record.total_requests = self.env['llm.request.log'].search_count([
                ('provider_id', '=', record.id)
            ])
    
    @api.depends('llm_request_log_ids')
    def _compute_success_rate(self):
        """Compute success rate percentage."""
        for record in self:
            total_requests = self.env['llm.request.log'].search_count([
                ('provider_id', '=', record.id)
            ])
            if total_requests > 0:
                successful_requests = self.env['llm.request.log'].search_count([
                    ('provider_id', '=', record.id),
                    ('status', '=', 'success')
                ])
                record.success_rate = (successful_requests / total_requests) * 100
            else:
                record.success_rate = 0.0
    
    def get_provider_config(self):
        """Get provider configuration as a dictionary."""
        self.ensure_one()
        config = {
            'name': self.name,
            'code': self.code,
            'api_base_url': self.api_base_url,
            'default_model': self.default_model_id.name,
            'is_active': self.is_active,
        }
        
        # Add provider-specific configuration
        if self.provider_specific_config:
            try:
                config.update(json.loads(self.provider_specific_config))
            except json.JSONDecodeError:
                _logger.error(f"Invalid JSON in provider_specific_config for provider {self.name}")
        
        return config
    
    def get_api_key(self):
        """Get the decrypted API key for this provider."""
        self.ensure_one()
        return self.api_key_id.get_decrypted_key()
    
    def test_connection(self):
        """Test the connection to the LLM provider."""
        self.ensure_one()
        
        try:
            # Get the appropriate service class
            service_model = f'llm.{self.code}.service'
            service = self.env[service_model]
            
            # Test with a simple request
            result = service.generate_text(
                prompt="Hello, this is a test message.",
                max_tokens=10
            )
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Test'),
                    'message': _('Successfully connected to %s') % self.name,
                    'type': 'success',
                }
            }
            
        except Exception as e:
            _logger.error(f"Connection test failed for provider {self.name}: {str(e)}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Test Failed'),
                    'message': _('Failed to connect to %s: %s') % (self.name, str(e)),
                    'type': 'danger',
                }
            }
    
    def name_get(self):
        """Custom name display for the provider."""
        result = []
        for record in self:
            name = f"{record.name} ({record.code})"
            if not record.is_active:
                name += " [Inactive]"
            result.append((record.id, name))
        return result 