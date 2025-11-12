from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import json
import logging
from abc import ABC, abstractmethod
import requests
from typing import Dict, List, Optional, Any, Union

_logger = logging.getLogger(__name__)


class LLMBaseService(models.AbstractModel):
    """Abstract base service for LLM provider implementations."""
    
    _name = 'llm.base.service'
    _description = 'LLM Base Service'
    
    # Abstract fields that must be implemented by concrete classes
    provider_code = fields.Char(compute='_compute_provider_code', store=True)
    provider_name = fields.Char(compute='_compute_provider_name', store=True)
    
    @api.depends()
    def _compute_provider_code(self):
        """Compute provider code from the model name."""
        for record in self:
            # Extract provider code from model name (e.g., 'llm.openai.service' -> 'openai')
            model_name = record._name
            if '.' in model_name:
                parts = model_name.split('.')
                if len(parts) >= 2:
                    record.provider_code = parts[1]
                else:
                    record.provider_code = 'unknown'
            else:
                record.provider_code = 'unknown'
    
    @api.depends('provider_code')
    def _compute_provider_name(self):
        """Compute provider name from provider code."""
        provider_names = {
            'openai': 'OpenAI',
            'gemini': 'Google Gemini',
            'claude': 'Anthropic Claude',
            'llama': 'Meta Llama',
            'deepseek': 'DeepSeek AI',
            'grok': 'xAI Grok',
        }
        for record in self:
            record.provider_name = provider_names.get(record.provider_code, 'Unknown')
    
    def get_active_provider(self):
        """Get the active provider configuration for this service."""
        provider = self.env['llm.provider'].search([
            ('code', '=', self.provider_code),
            ('is_active', '=', True)
        ], limit=1)
        
        if not provider:
            raise UserError(_('No active provider found for %s') % self.provider_name)
        
        return provider
    
    def get_api_key(self):
        """Get the API key for this provider."""
        provider = self.get_active_provider()
        return provider.get_api_key()
    
    def get_base_url(self):
        """Get the base URL for this provider."""
        provider = self.get_active_provider()
        return provider.api_base_url
    
    def get_default_model(self):
        """Get the default model for this provider."""
        provider = self.get_active_provider()
        return provider.default_model_id.model_code
    
    def log_request(self, request_data: Dict, response_data: Dict, status: str, error_message: str = None):
        """Log LLM request and response for monitoring."""
        provider = self.get_active_provider()
        
        log_data = {
            'provider_id': provider.id,
            'request_data': json.dumps(request_data, default=str),
            'response_data': json.dumps(response_data, default=str) if response_data else None,
            'status': status,
            'error_message': error_message,
            'user_id': self.env.user.id,
        }
        
        self.env['llm.request.log'].create(log_data)
    
    def handle_rate_limits(self, response):
        """Handle rate limit headers and implement backoff strategy."""
        if response.status_code == 429:
            # Rate limit exceeded
            retry_after = response.headers.get('Retry-After', 60)
            _logger.warning(f"Rate limit exceeded for {self.provider_name}. Retry after {retry_after} seconds.")
            raise UserError(_('Rate limit exceeded. Please try again later.'))
        
        # Monitor remaining quota
        remaining_requests = response.headers.get('x-ratelimit-remaining-requests')
        remaining_tokens = response.headers.get('x-ratelimit-remaining-tokens')
        
        if remaining_requests and int(remaining_requests) < 10:
            _logger.warning(f"Low remaining requests for {self.provider_name}: {remaining_requests}")
        
        if remaining_tokens and int(remaining_tokens) < 1000:
            _logger.warning(f"Low remaining tokens for {self.provider_name}: {remaining_tokens}")
    
    def validate_parameters(self, **kwargs):
        """Validate common LLM parameters."""
        validated_params = {}
        
        # Temperature validation
        if 'temperature' in kwargs:
            temp = kwargs['temperature']
            if not isinstance(temp, (int, float)) or temp < 0 or temp > 2:
                raise ValidationError(_('Temperature must be between 0 and 2'))
            validated_params['temperature'] = temp
        
        # Max tokens validation
        if 'max_tokens' in kwargs:
            max_tokens = kwargs['max_tokens']
            if not isinstance(max_tokens, int) or max_tokens <= 0:
                raise ValidationError(_('Max tokens must be a positive integer'))
            validated_params['max_tokens'] = max_tokens
        
        # Top P validation
        if 'top_p' in kwargs:
            top_p = kwargs['top_p']
            if not isinstance(top_p, (int, float)) or top_p < 0 or top_p > 1:
                raise ValidationError(_('Top P must be between 0 and 1'))
            validated_params['top_p'] = top_p
        
        # Stop sequences validation
        if 'stop_sequences' in kwargs:
            stop_sequences = kwargs['stop_sequences']
            if not isinstance(stop_sequences, list):
                raise ValidationError(_('Stop sequences must be a list'))
            validated_params['stop_sequences'] = stop_sequences
        
        # Stream validation
        if 'stream' in kwargs:
            stream = kwargs['stream']
            if not isinstance(stream, bool):
                raise ValidationError(_('Stream must be a boolean'))
            validated_params['stream'] = stream
        
        return validated_params
    
    @abstractmethod
    def generate_text(self, prompt: str, model: str = None, **kwargs) -> str:
        """
        Generate text using the LLM.
        
        Args:
            prompt: The input text prompt
            model: The model to use (optional, uses default if not specified)
            **kwargs: Additional parameters (temperature, max_tokens, etc.)
        
        Returns:
            Generated text string
        """
        pass
    
    @abstractmethod
    def chat_completion(self, messages: List[Dict], model: str = None, **kwargs) -> Dict:
        """
        Generate chat completion using the LLM.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'
            model: The model to use (optional, uses default if not specified)
            **kwargs: Additional parameters
        
        Returns:
            Response dictionary with generated content
        """
        pass
    
    @abstractmethod
    def get_embeddings(self, text: str, model: str = None) -> List[float]:
        """
        Get embeddings for the given text.
        
        Args:
            text: Input text to embed
            model: The embedding model to use (optional)
        
        Returns:
            List of embedding values
        """
        pass
    
    def call_function(self, function_name: str, arguments: Dict) -> Any:
        """
        Call a registered function/tool.
        
        Args:
            function_name: Name of the function to call
            arguments: Arguments to pass to the function
        
        Returns:
            Result of the function call
        """
        # This will be implemented by the function calling framework
        raise NotImplementedError(_('Function calling not implemented for this provider'))
    
    def get_available_functions(self) -> List[Dict]:
        """
        Get list of available functions/tools.
        
        Returns:
            List of function definitions
        """
        # This will be implemented by the function calling framework
        return []
    
    def stream_response(self, prompt: str, model: str = None, **kwargs):
        """
        Stream response from the LLM.
        
        Args:
            prompt: The input text prompt
            model: The model to use
            **kwargs: Additional parameters
        
        Yields:
            Response chunks
        """
        # Default implementation - override in concrete classes
        response = self.generate_text(prompt, model, **kwargs)
        yield response
    
    def estimate_tokens(self, text: str) -> int:
        """
        Estimate the number of tokens in the given text.
        
        Args:
            text: Input text
        
        Returns:
            Estimated token count
        """
        # Simple estimation: ~4 characters per token
        return len(text) // 4
    
    def get_model_info(self, model: str = None) -> Dict:
        """
        Get information about a specific model.
        
        Args:
            model: Model name (optional, uses default if not specified)
        
        Returns:
            Model information dictionary
        """
        if not model:
            model = self.get_default_model()
        
        model_record = self.env['llm.provider.model'].get_model_by_code(
            model, self.provider_code
        )
        
        if model_record:
            return model_record.get_model_config()
        else:
            return {'name': model, 'model_code': model}
    
    def test_connection(self) -> bool:
        """
        Test the connection to the LLM provider.
        
        Returns:
            True if connection is successful
        """
        try:
            # Simple test with minimal tokens
            result = self.generate_text(
                prompt="Test",
                max_tokens=5
            )
            return bool(result and len(result.strip()) > 0)
        except Exception as e:
            _logger.error(f"Connection test failed for {self.provider_name}: {str(e)}")
            return False 