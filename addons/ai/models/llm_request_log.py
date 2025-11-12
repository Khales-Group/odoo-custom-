from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import json
import logging

_logger = logging.getLogger(__name__)


class LLMRequestLog(models.Model):
    """Model for logging LLM API requests and responses."""
    
    _name = 'llm.request.log'
    _description = 'LLM Request Log'
    _order = 'create_date desc'
    
    # Basic information
    provider_id = fields.Many2one(
        'llm.provider',
        string='Provider',
        required=True,
        ondelete='cascade',
        help='LLM provider used for this request'
    )
    
    user_id = fields.Many2one(
        'res.users',
        string='User',
        required=True,
        default=lambda self: self.env.user,
        help='User who made the request'
    )
    
    # Request details
    request_data = fields.Text(
        string='Request Data',
        help='JSON representation of the request sent to the LLM'
    )
    
    response_data = fields.Text(
        string='Response Data',
        help='JSON representation of the response from the LLM'
    )
    
    # Status and timing
    status = fields.Selection([
        ('success', 'Success'),
        ('error', 'Error'),
        ('timeout', 'Timeout'),
        ('rate_limited', 'Rate Limited'),
    ], string='Status', required=True, default='success', help='Status of the request')
    
    error_message = fields.Text(
        string='Error Message',
        help='Error message if the request failed'
    )
    
    # Performance metrics
    request_duration = fields.Float(
        string='Request Duration (seconds)',
        help='Time taken to complete the request'
    )
    
    input_tokens = fields.Integer(
        string='Input Tokens',
        help='Number of tokens in the input'
    )
    
    output_tokens = fields.Integer(
        string='Output Tokens',
        help='Number of tokens in the output'
    )
    
    total_tokens = fields.Integer(
        string='Total Tokens',
        compute='_compute_total_tokens',
        store=True,
        help='Total number of tokens (input + output)'
    )
    
    # Cost tracking
    estimated_cost = fields.Float(
        string='Estimated Cost (USD)',
        help='Estimated cost of the request in USD'
    )
    
    # Metadata
    model_used = fields.Char(
        string='Model Used',
        help='LLM model used for this request'
    )
    
    request_type = fields.Selection([
        ('text_generation', 'Text Generation'),
        ('chat_completion', 'Chat Completion'),
        ('embeddings', 'Embeddings'),
        ('function_call', 'Function Call'),
        ('streaming', 'Streaming'),
    ], string='Request Type', help='Type of LLM request')
    
    # Computed fields
    @api.depends('input_tokens', 'output_tokens')
    def _compute_total_tokens(self):
        """Compute total tokens from input and output tokens."""
        for record in self:
            record.total_tokens = (record.input_tokens or 0) + (record.output_tokens or 0)
    
    def name_get(self):
        """Custom name display for request logs."""
        result = []
        for record in self:
            name = f"{record.provider_id.name} - {record.status} - {record.create_date.strftime('%Y-%m-%d %H:%M')}"
            result.append((record.id, name))
        return result
    
    def get_request_summary(self):
        """Get a summary of the request for display."""
        self.ensure_one()
        
        try:
            if self.request_data:
                request_json = json.loads(self.request_data)
                if 'prompt' in request_json:
                    return request_json['prompt'][:100] + "..." if len(request_json['prompt']) > 100 else request_json['prompt']
                elif 'messages' in request_json and request_json['messages']:
                    last_message = request_json['messages'][-1]
                    if 'content' in last_message:
                        return last_message['content'][:100] + "..." if len(last_message['content']) > 100 else last_message['content']
        except (json.JSONDecodeError, KeyError, IndexError):
            pass
        
        return "Request data not available"
    
    def get_response_summary(self):
        """Get a summary of the response for display."""
        self.ensure_one()
        
        if self.status != 'success' or not self.response_data:
            return self.error_message or "No response data"
        
        try:
            response_json = json.loads(self.response_data)
            
            # Handle different response formats
            if 'choices' in response_json and response_json['choices']:
                choice = response_json['choices'][0]
                if 'text' in choice:
                    return choice['text'][:100] + "..." if len(choice['text']) > 100 else choice['text']
                elif 'message' in choice and 'content' in choice['message']:
                    return choice['message']['content'][:100] + "..." if len(choice['message']['content']) > 100 else choice['message']['content']
            
            elif 'content' in response_json and response_json['content']:
                content = response_json['content'][0]
                if 'text' in content:
                    return content['text'][:100] + "..." if len(content['text']) > 100 else content['text']
            
            elif 'candidates' in response_json and response_json['candidates']:
                candidate = response_json['candidates'][0]
                if 'content' in candidate and candidate['content']['parts']:
                    text = candidate['content']['parts'][0]['text']
                    return text[:100] + "..." if len(text) > 100 else text
                    
        except (json.JSONDecodeError, KeyError, IndexError):
            pass
        
        return "Response data not available"
    
    def calculate_estimated_cost(self):
        """Calculate estimated cost based on token usage and provider pricing."""
        self.ensure_one()
        
        if not self.total_tokens or not self.provider_id:
            return 0.0
        
        # Get model pricing information
        model_record = self.env['llm.provider.model'].search([
            ('model_code', '=', self.model_used),
            ('provider_type', '=', self.provider_id.code)
        ], limit=1)
        
        if not model_record:
            return 0.0
        
        # Calculate cost based on input and output tokens
        input_cost = (self.input_tokens or 0) * (model_record.input_cost_per_1k_tokens or 0) / 1000
        output_cost = (self.output_tokens or 0) * (model_record.output_cost_per_1k_tokens or 0) / 1000
        
        return input_cost + output_cost
    
    @api.model
    def cleanup_old_logs(self, days_to_keep=30):
        """Clean up old log entries to prevent database bloat."""
        from datetime import datetime, timedelta
        
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        
        old_logs = self.search([
            ('create_date', '<', cutoff_date)
        ])
        
        count = len(old_logs)
        old_logs.unlink()
        
        _logger.info(f"Cleaned up {count} old LLM request logs older than {days_to_keep} days")
        return count
    
    @api.model
    def get_usage_statistics(self, provider_id=None, user_id=None, date_from=None, date_to=None):
        """Get usage statistics for monitoring and reporting."""
        domain = []
        
        if provider_id:
            domain.append(('provider_id', '=', provider_id))
        if user_id:
            domain.append(('user_id', '=', user_id))
        if date_from:
            domain.append(('create_date', '>=', date_from))
        if date_to:
            domain.append(('create_date', '<=', date_to))
        
        logs = self.search(domain)
        
        stats = {
            'total_requests': len(logs),
            'successful_requests': len(logs.filtered(lambda l: l.status == 'success')),
            'failed_requests': len(logs.filtered(lambda l: l.status == 'error')),
            'total_tokens': sum(logs.mapped('total_tokens')),
            'total_cost': sum(logs.mapped('estimated_cost')),
            'avg_duration': sum(logs.mapped('request_duration')) / len(logs) if logs else 0,
        }
        
        return stats
    
    def action_view_provider(self):
        """Action to view the provider details."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Provider Details'),
            'res_model': 'llm.provider',
            'res_id': self.provider_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
    
    def action_view_user(self):
        """Action to view the user details."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('User Details'),
            'res_model': 'res.users',
            'res_id': self.user_id.id,
            'view_mode': 'form',
            'target': 'current',
        } 