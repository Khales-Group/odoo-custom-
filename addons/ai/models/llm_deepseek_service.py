from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import json
import logging
import requests
from typing import Dict, List, Optional, Any, Union
import time

_logger = logging.getLogger(__name__)


class LLMDeepSeekService(models.Model):
    """Service implementation for DeepSeek models via various APIs."""
    
    _name = 'llm.deepseek.service'
    _description = 'DeepSeek Service'
    _inherit = 'llm.base.service'
    
    # Provider-specific configuration
    api_type = fields.Selection([
        ('deepseek', 'DeepSeek AI'),
        ('together', 'Together AI'),
        ('replicate', 'Replicate'),
        ('huggingface', 'Hugging Face'),
        ('custom', 'Custom API'),
    ], string='API Type', required=True, default='deepseek',
       help='Type of API to use for DeepSeek models')
    
    custom_api_url = fields.Char(
        string='Custom API URL',
        help='Custom API endpoint URL (for custom API type)'
    )
    
    def get_api_endpoint(self, model: str = None) -> str:
        """Get the appropriate API endpoint based on API type."""
        if self.api_type == 'deepseek':
            return 'https://api.deepseek.com/v1'
        elif self.api_type == 'together':
            return 'https://api.together.xyz/v1'
        elif self.api_type == 'replicate':
            return 'https://api.replicate.com/v1'
        elif self.api_type == 'huggingface':
            return 'https://api-inference.huggingface.co'
        elif self.api_type == 'custom':
            return self.custom_api_url or self.get_base_url()
        else:
            return self.get_base_url()
    
    def get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        api_key = self.get_api_key()
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        }
        
        # Add provider-specific headers
        if self.api_type == 'deepseek':
            headers['User-Agent'] = 'Odoo-AI-Automation/1.0'
        elif self.api_type == 'together':
            headers['User-Agent'] = 'Odoo-AI-Automation/1.0'
        elif self.api_type == 'replicate':
            headers['User-Agent'] = 'Odoo-AI-Automation/1.0'
        elif self.api_type == 'huggingface':
            headers['User-Agent'] = 'Odoo-AI-Automation/1.0'
        
        return headers
    
    def get_model_mapping(self, model: str = None) -> str:
        """Map Odoo model codes to provider-specific model names."""
        if not model:
            model = self.get_default_model()
        
        # DeepSeek AI model mappings
        deepseek_models = {
            'deepseek-chat': 'deepseek-chat',
            'deepseek-coder': 'deepseek-coder',
            'deepseek-coder-instruct': 'deepseek-coder-instruct',
            'deepseek-coder-33b-instruct': 'deepseek-coder-33b-instruct',
            'deepseek-coder-6.7b-instruct': 'deepseek-coder-6.7b-instruct',
            'deepseek-coder-1.3b-instruct': 'deepseek-coder-1.3b-instruct',
            'deepseek-llm-7b-chat': 'deepseek-llm-7b-chat',
            'deepseek-llm-67b-chat': 'deepseek-llm-67b-chat',
            'deepseek-math-7b-instruct': 'deepseek-math-7b-instruct',
            'deepseek-math-67b-instruct': 'deepseek-math-67b-instruct',
        }
        
        # Together AI model mappings
        together_models = {
            'deepseek-chat': 'deepseek-ai/deepseek-chat',
            'deepseek-coder': 'deepseek-ai/deepseek-coder',
            'deepseek-coder-instruct': 'deepseek-ai/deepseek-coder-instruct',
            'deepseek-coder-33b-instruct': 'deepseek-ai/deepseek-coder-33b-instruct',
            'deepseek-coder-6.7b-instruct': 'deepseek-ai/deepseek-coder-6.7b-instruct',
            'deepseek-coder-1.3b-instruct': 'deepseek-ai/deepseek-coder-1.3b-instruct',
            'deepseek-llm-7b-chat': 'deepseek-ai/deepseek-llm-7b-chat',
            'deepseek-llm-67b-chat': 'deepseek-ai/deepseek-llm-67b-chat',
            'deepseek-math-7b-instruct': 'deepseek-ai/deepseek-math-7b-instruct',
            'deepseek-math-67b-instruct': 'deepseek-ai/deepseek-math-67b-instruct',
        }
        
        # Replicate model mappings
        replicate_models = {
            'deepseek-chat': 'deepseek-ai/deepseek-chat',
            'deepseek-coder': 'deepseek-ai/deepseek-coder',
            'deepseek-coder-instruct': 'deepseek-ai/deepseek-coder-instruct',
            'deepseek-coder-33b-instruct': 'deepseek-ai/deepseek-coder-33b-instruct',
            'deepseek-coder-6.7b-instruct': 'deepseek-ai/deepseek-coder-6.7b-instruct',
            'deepseek-coder-1.3b-instruct': 'deepseek-ai/deepseek-coder-1.3b-instruct',
            'deepseek-llm-7b-chat': 'deepseek-ai/deepseek-llm-7b-chat',
            'deepseek-llm-67b-chat': 'deepseek-ai/deepseek-llm-67b-chat',
            'deepseek-math-7b-instruct': 'deepseek-ai/deepseek-math-7b-instruct',
            'deepseek-math-67b-instruct': 'deepseek-ai/deepseek-math-67b-instruct',
        }
        
        # Hugging Face model mappings
        huggingface_models = {
            'deepseek-chat': 'deepseek-ai/deepseek-chat',
            'deepseek-coder': 'deepseek-ai/deepseek-coder',
            'deepseek-coder-instruct': 'deepseek-ai/deepseek-coder-instruct',
            'deepseek-coder-33b-instruct': 'deepseek-ai/deepseek-coder-33b-instruct',
            'deepseek-coder-6.7b-instruct': 'deepseek-ai/deepseek-coder-6.7b-instruct',
            'deepseek-coder-1.3b-instruct': 'deepseek-ai/deepseek-coder-1.3b-instruct',
            'deepseek-llm-7b-chat': 'deepseek-ai/deepseek-llm-7b-chat',
            'deepseek-llm-67b-chat': 'deepseek-ai/deepseek-llm-67b-chat',
            'deepseek-math-7b-instruct': 'deepseek-ai/deepseek-math-7b-instruct',
            'deepseek-math-67b-instruct': 'deepseek-ai/deepseek-math-67b-instruct',
        }
        
        # Return the appropriate mapping based on API type
        if self.api_type == 'deepseek':
            return deepseek_models.get(model, model)
        elif self.api_type == 'together':
            return together_models.get(model, model)
        elif self.api_type == 'replicate':
            return replicate_models.get(model, model)
        elif self.api_type == 'huggingface':
            return huggingface_models.get(model, model)
        else:
            return model
    
    def generate_text(self, prompt: str, model: str = None, **kwargs) -> str:
        """Generate text using DeepSeek models."""
        try:
            model = model or self.get_default_model()
            endpoint = self.get_api_endpoint(model)
            headers = self.get_headers()
            
            # Prepare request data based on API type
            if self.api_type == 'deepseek':
                request_data = self._prepare_deepseek_request(prompt, model, **kwargs)
            elif self.api_type == 'together':
                request_data = self._prepare_together_request(prompt, model, **kwargs)
            elif self.api_type == 'replicate':
                request_data = self._prepare_replicate_request(prompt, model, **kwargs)
            elif self.api_type == 'huggingface':
                request_data = self._prepare_huggingface_request(prompt, model, **kwargs)
            else:
                request_data = self._prepare_custom_request(prompt, model, **kwargs)
            
            # Make API request
            url = f"{endpoint}/chat/completions" if self.api_type == 'deepseek' else f"{endpoint}/completions"
            response = requests.post(url, headers=headers, json=request_data, timeout=60)
            
            if response.status_code == 200:
                response_data = response.json()
                result = self._parse_response(response_data)
                self.log_request(request_data, response_data, 'success')
                return result
            else:
                error_msg = f"API request failed: {response.status_code} - {response.text}"
                self.log_request(request_data, {'error': error_msg}, 'error', error_msg)
                raise UserError(_(error_msg))
                
        except Exception as e:
            _logger.error(f"Error in DeepSeek text generation: {str(e)}")
            raise UserError(_('Error generating text: %s') % str(e))
    
    def chat_completion(self, messages: List[Dict], model: str = None, **kwargs) -> Dict:
        """Get chat completion using DeepSeek models."""
        try:
            model = model or self.get_default_model()
            endpoint = self.get_api_endpoint(model)
            headers = self.get_headers()
            
            # Prepare request data based on API type
            if self.api_type == 'deepseek':
                request_data = self._prepare_deepseek_chat_request(messages, model, **kwargs)
            elif self.api_type == 'together':
                request_data = self._prepare_together_chat_request(messages, model, **kwargs)
            elif self.api_type == 'replicate':
                # Replicate doesn't support chat directly, convert to prompt
                prompt = self._messages_to_prompt(messages)
                request_data = self._prepare_replicate_request(prompt, model, **kwargs)
            elif self.api_type == 'huggingface':
                # Hugging Face doesn't support chat directly, convert to prompt
                prompt = self._messages_to_prompt(messages)
                request_data = self._prepare_huggingface_request(prompt, model, **kwargs)
            else:
                request_data = self._prepare_custom_request(self._messages_to_prompt(messages), model, **kwargs)
            
            # Make API request
            url = f"{endpoint}/chat/completions"
            response = requests.post(url, headers=headers, json=request_data, timeout=60)
            
            if response.status_code == 200:
                response_data = response.json()
                result = self._parse_chat_response(response_data)
                self.log_request(request_data, response_data, 'success')
                return result
            else:
                error_msg = f"API request failed: {response.status_code} - {response.text}"
                self.log_request(request_data, {'error': error_msg}, 'error', error_msg)
                raise UserError(_(error_msg))
                
        except Exception as e:
            _logger.error(f"Error in DeepSeek chat completion: {str(e)}")
            raise UserError(_('Error in chat completion: %s') % str(e))
    
    def get_embeddings(self, text: str, model: str = None) -> List[float]:
        """Get embeddings using DeepSeek models (if supported)."""
        try:
            model = model or self.get_default_model()
            endpoint = self.get_api_endpoint(model)
            headers = self.get_headers()
            
            # DeepSeek doesn't currently support embeddings via their API
            # This is a placeholder for future implementation
            raise UserError(_('Embeddings are not currently supported by DeepSeek API'))
            
        except Exception as e:
            _logger.error(f"Error in DeepSeek embeddings: {str(e)}")
            raise UserError(_('Error getting embeddings: %s') % str(e))
    
    def _prepare_deepseek_request(self, prompt: str, model: str, **kwargs) -> Dict:
        """Prepare request data for DeepSeek AI API."""
        return {
            'model': self.get_model_mapping(model),
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': kwargs.get('max_tokens', 1000),
            'temperature': kwargs.get('temperature', 0.7),
            'top_p': kwargs.get('top_p', 1.0),
            'stream': kwargs.get('stream', False),
        }
    
    def _prepare_deepseek_chat_request(self, messages: List[Dict], model: str, **kwargs) -> Dict:
        """Prepare chat request data for DeepSeek AI API."""
        return {
            'model': self.get_model_mapping(model),
            'messages': messages,
            'max_tokens': kwargs.get('max_tokens', 1000),
            'temperature': kwargs.get('temperature', 0.7),
            'top_p': kwargs.get('top_p', 1.0),
            'stream': kwargs.get('stream', False),
        }
    
    def _prepare_together_request(self, prompt: str, model: str, **kwargs) -> Dict:
        """Prepare request data for Together AI API."""
        return {
            'model': self.get_model_mapping(model),
            'prompt': prompt,
            'max_tokens': kwargs.get('max_tokens', 1000),
            'temperature': kwargs.get('temperature', 0.7),
            'top_p': kwargs.get('top_p', 1.0),
            'stream': kwargs.get('stream', False),
        }
    
    def _prepare_together_chat_request(self, messages: List[Dict], model: str, **kwargs) -> Dict:
        """Prepare chat request data for Together AI API."""
        return {
            'model': self.get_model_mapping(model),
            'messages': messages,
            'max_tokens': kwargs.get('max_tokens', 1000),
            'temperature': kwargs.get('temperature', 0.7),
            'top_p': kwargs.get('top_p', 1.0),
            'stream': kwargs.get('stream', False),
        }
    
    def _prepare_replicate_request(self, prompt: str, model: str, **kwargs) -> Dict:
        """Prepare request data for Replicate API."""
        return {
            'version': self.get_model_mapping(model),
            'input': {
                'prompt': prompt,
                'max_tokens': kwargs.get('max_tokens', 1000),
                'temperature': kwargs.get('temperature', 0.7),
                'top_p': kwargs.get('top_p', 1.0),
            }
        }
    
    def _prepare_huggingface_request(self, prompt: str, model: str, **kwargs) -> Dict:
        """Prepare request data for Hugging Face API."""
        return {
            'inputs': prompt,
            'parameters': {
                'max_new_tokens': kwargs.get('max_tokens', 1000),
                'temperature': kwargs.get('temperature', 0.7),
                'top_p': kwargs.get('top_p', 1.0),
                'do_sample': True,
            }
        }
    
    def _prepare_custom_request(self, prompt: str, model: str, **kwargs) -> Dict:
        """Prepare request data for custom API."""
        return {
            'model': self.get_model_mapping(model),
            'prompt': prompt,
            'max_tokens': kwargs.get('max_tokens', 1000),
            'temperature': kwargs.get('temperature', 0.7),
            'top_p': kwargs.get('top_p', 1.0),
        }
    
    def _parse_response(self, response_data: Dict) -> str:
        """Parse response data from API."""
        if self.api_type == 'deepseek':
            return response_data.get('choices', [{}])[0].get('message', {}).get('content', '')
        elif self.api_type == 'together':
            return response_data.get('choices', [{}])[0].get('text', '')
        elif self.api_type == 'replicate':
            return response_data.get('output', [''])[0] if isinstance(response_data.get('output'), list) else response_data.get('output', '')
        elif self.api_type == 'huggingface':
            return response_data[0].get('generated_text', '') if response_data else ''
        else:
            return response_data.get('choices', [{}])[0].get('text', '')
    
    def _parse_chat_response(self, response_data: Dict) -> Dict:
        """Parse chat response data from API."""
        if self.api_type == 'deepseek':
            choice = response_data.get('choices', [{}])[0]
            return {
                'content': choice.get('message', {}).get('content', ''),
                'role': choice.get('message', {}).get('role', 'assistant'),
                'finish_reason': choice.get('finish_reason', ''),
                'usage': response_data.get('usage', {}),
            }
        elif self.api_type == 'together':
            choice = response_data.get('choices', [{}])[0]
            return {
                'content': choice.get('message', {}).get('content', ''),
                'role': choice.get('message', {}).get('role', 'assistant'),
                'finish_reason': choice.get('finish_reason', ''),
                'usage': response_data.get('usage', {}),
            }
        else:
            # For other providers, return a simplified response
            return {
                'content': self._parse_response(response_data),
                'role': 'assistant',
                'finish_reason': 'stop',
                'usage': response_data.get('usage', {}),
            }
    
    def _messages_to_prompt(self, messages: List[Dict]) -> str:
        """Convert chat messages to a single prompt string."""
        prompt = ""
        for message in messages:
            role = message.get('role', 'user')
            content = message.get('content', '')
            if role == 'system':
                prompt += f"System: {content}\n\n"
            elif role == 'user':
                prompt += f"User: {content}\n\n"
            elif role == 'assistant':
                prompt += f"Assistant: {content}\n\n"
        prompt += "Assistant: "
        return prompt
    
    def test_connection(self) -> bool:
        """Test the connection to the DeepSeek API."""
        try:
            # Try a simple text generation request
            response = self.generate_text(
                prompt="Hello, this is a test message.",
                max_tokens=10,
                temperature=0.1
            )
            
            if response and len(response.strip()) > 0:
                return True
            else:
                raise UserError(_('Test failed: Empty response received'))
                
        except Exception as e:
            _logger.error(f"DeepSeek connection test failed: {str(e)}")
            raise UserError(_('Connection test failed: %s') % str(e))
    
    def get_available_models(self) -> List[Dict]:
        """Get list of available DeepSeek models."""
        models = [
            {
                'code': 'deepseek-chat',
                'name': 'DeepSeek Chat',
                'description': 'General purpose chat model',
                'context_length': 32768,
                'supports_chat': True,
                'supports_text_generation': True,
            },
            {
                'code': 'deepseek-coder',
                'name': 'DeepSeek Coder',
                'description': 'Specialized for code generation and programming tasks',
                'context_length': 16384,
                'supports_chat': True,
                'supports_text_generation': True,
            },
            {
                'code': 'deepseek-coder-instruct',
                'name': 'DeepSeek Coder Instruct',
                'description': 'Instruction-tuned version for code generation',
                'context_length': 16384,
                'supports_chat': True,
                'supports_text_generation': True,
            },
            {
                'code': 'deepseek-coder-33b-instruct',
                'name': 'DeepSeek Coder 33B Instruct',
                'description': 'Large instruction-tuned model for complex coding tasks',
                'context_length': 16384,
                'supports_chat': True,
                'supports_text_generation': True,
            },
            {
                'code': 'deepseek-coder-6.7b-instruct',
                'name': 'DeepSeek Coder 6.7B Instruct',
                'description': 'Medium-sized model for code generation',
                'context_length': 16384,
                'supports_chat': True,
                'supports_text_generation': True,
            },
            {
                'code': 'deepseek-coder-1.3b-instruct',
                'name': 'DeepSeek Coder 1.3B Instruct',
                'description': 'Small, fast model for basic code generation',
                'context_length': 16384,
                'supports_chat': True,
                'supports_text_generation': True,
            },
            {
                'code': 'deepseek-llm-7b-chat',
                'name': 'DeepSeek LLM 7B Chat',
                'description': '7B parameter chat model',
                'context_length': 32768,
                'supports_chat': True,
                'supports_text_generation': True,
            },
            {
                'code': 'deepseek-llm-67b-chat',
                'name': 'DeepSeek LLM 67B Chat',
                'description': '67B parameter chat model for complex reasoning',
                'context_length': 32768,
                'supports_chat': True,
                'supports_text_generation': True,
            },
            {
                'code': 'deepseek-math-7b-instruct',
                'name': 'DeepSeek Math 7B Instruct',
                'description': 'Specialized for mathematical reasoning and problem solving',
                'context_length': 32768,
                'supports_chat': True,
                'supports_text_generation': True,
            },
            {
                'code': 'deepseek-math-67b-instruct',
                'name': 'DeepSeek Math 67B Instruct',
                'description': 'Large model specialized for advanced mathematics',
                'context_length': 32768,
                'supports_chat': True,
                'supports_text_generation': True,
            },
        ]
        
        return models 