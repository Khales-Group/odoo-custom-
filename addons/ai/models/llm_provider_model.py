from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class LLMProviderModel(models.Model):
    """Model for managing specific LLM models available from providers."""
    
    _name = 'llm.provider.model'
    _description = 'LLM Provider Model'
    _order = 'provider_type, name'
    
    name = fields.Char(
        string='Model Name',
        required=True,
        help='Name of the LLM model (e.g., "gpt-4o", "gemini-2.5-pro")'
    )
    
    provider_type = fields.Selection([
        ('openai', 'OpenAI'),
        ('gemini', 'Google Gemini'),
        ('claude', 'Anthropic Claude'),
        ('llama', 'Meta Llama'),
        ('grok', 'xAI Grok'),
        ('other', 'Other'),
    ], string='Provider Type', required=True, help='Type of LLM provider')
    
    model_code = fields.Char(
        string='Model Code',
        required=True,
        help='Programmatic identifier for the model (e.g., "gpt-4o", "gemini-2.5-pro")'
    )
    
    is_active = fields.Boolean(
        string='Active',
        default=True,
        help='Enable or disable this model'
    )
    
    # Model capabilities
    supports_chat = fields.Boolean(
        string='Supports Chat',
        default=True,
        help='Whether this model supports chat completion'
    )
    
    supports_text_generation = fields.Boolean(
        string='Supports Text Generation',
        default=True,
        help='Whether this model supports text generation'
    )
    
    supports_embeddings = fields.Boolean(
        string='Supports Embeddings',
        default=False,
        help='Whether this model supports embeddings'
    )
    
    supports_streaming = fields.Boolean(
        string='Supports Streaming',
        default=True,
        help='Whether this model supports streaming responses'
    )
    
    supports_function_calling = fields.Boolean(
        string='Supports Function Calling',
        default=False,
        help='Whether this model supports function calling/tools'
    )
    
    # Model specifications
    max_tokens = fields.Integer(
        string='Max Tokens',
        help='Maximum number of tokens this model can handle'
    )
    
    context_length = fields.Integer(
        string='Context Length',
        help='Maximum context length in tokens'
    )
    
    # Pricing information (for reference)
    input_cost_per_1k_tokens = fields.Float(
        string='Input Cost per 1K Tokens',
        help='Cost per 1000 input tokens (for reference)'
    )
    
    output_cost_per_1k_tokens = fields.Float(
        string='Output Cost per 1K Tokens',
        help='Cost per 1000 output tokens (for reference)'
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.ref('base.USD'),
        help='Currency for cost information'
    )
    
    # Model description
    description = fields.Text(
        string='Description',
        help='Description of the model and its capabilities'
    )
    
    # Constraints
    _sql_constraints = [
        ('unique_model_code', 'unique(model_code, provider_type)', 
         'Model code must be unique per provider type!'),
    ]
    
    @api.constrains('max_tokens', 'context_length')
    def _check_token_limits(self):
        """Validate token limits."""
        for record in self:
            if record.max_tokens and record.context_length:
                if record.max_tokens > record.context_length:
                    raise ValidationError(_('Max tokens cannot exceed context length.'))
    
    def get_model_config(self):
        """Get model configuration as a dictionary."""
        self.ensure_one()
        return {
            'name': self.name,
            'model_code': self.model_code,
            'provider_type': self.provider_type,
            'supports_chat': self.supports_chat,
            'supports_text_generation': self.supports_text_generation,
            'supports_embeddings': self.supports_embeddings,
            'supports_streaming': self.supports_streaming,
            'supports_function_calling': self.supports_function_calling,
            'max_tokens': self.max_tokens,
            'context_length': self.context_length,
        }
    
    def name_get(self):
        """Custom name display for models."""
        result = []
        for record in self:
            name = f"{record.name} ({record.provider_type})"
            if not record.is_active:
                name += " [Inactive]"
            result.append((record.id, name))
        return result
    
    @api.model
    def get_available_models(self, provider_type=None):
        """Get available models, optionally filtered by provider type."""
        domain = [('is_active', '=', True)]
        if provider_type:
            domain.append(('provider_type', '=', provider_type))
        
        return self.search(domain)
    
    @api.model
    def get_model_by_code(self, model_code, provider_type=None):
        """Get a specific model by its code."""
        domain = [('model_code', '=', model_code), ('is_active', '=', True)]
        if provider_type:
            domain.append(('provider_type', '=', provider_type))
        
        return self.search(domain, limit=1) 