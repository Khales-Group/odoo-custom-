from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import json
import logging
import requests
from typing import Dict, List, Optional, Any, Union

_logger = logging.getLogger(__name__)


class LLMOpenAIService(models.Model):
    """OpenAI LLM service implementation."""
    
    _name = 'llm.openai.service'
    _description = 'OpenAI LLM Service'
    _inherit = 'llm.base.service'
    
    def generate_text(self, prompt: str, model: str = None, **kwargs) -> str:
        """Generate text using OpenAI's completion API."""
        if not model:
            model = self.get_default_model()
        
        # Validate parameters
        validated_params = self.validate_parameters(**kwargs)
        
        # Prepare request data
        request_data = {
            'model': model,
            'prompt': prompt,
            **validated_params
        }
        
        # Add provider-specific configuration
        provider = self.get_active_provider()
        if provider.provider_specific_config:
            try:
                config = json.loads(provider.provider_specific_config)
                if 'organization_id' in config:
                    request_data['organization'] = config['organization_id']
            except json.JSONDecodeError:
                _logger.error(f"Invalid provider config for OpenAI: {provider.provider_specific_config}")
        
        try:
            # Make API request
            headers = {
                'Authorization': f'Bearer {self.get_api_key()}',
                'Content-Type': 'application/json',
            }
            
            response = requests.post(
                f"{self.get_base_url()}/completions",
                headers=headers,
                json=request_data,
                timeout=30
            )
            
            # Handle rate limits
            self.handle_rate_limits(response)
            
            if response.status_code == 200:
                response_data = response.json()
                generated_text = response_data['choices'][0]['text'].strip()
                
                # Log successful request
                self.log_request(request_data, response_data, 'success')
                
                return generated_text
            else:
                error_data = response.json() if response.content else {}
                error_message = error_data.get('error', {}).get('message', f'HTTP {response.status_code}')
                
                # Log failed request
                self.log_request(request_data, error_data, 'error', error_message)
                
                raise UserError(_('OpenAI API error: %s') % error_message)
                
        except requests.exceptions.RequestException as e:
            error_message = f"Network error: {str(e)}"
            self.log_request(request_data, {}, 'error', error_message)
            raise UserError(_('Network error: %s') % str(e))
        except Exception as e:
            error_message = f"Unexpected error: {str(e)}"
            self.log_request(request_data, {}, 'error', error_message)
            raise UserError(_('Unexpected error: %s') % str(e))
    
    def chat_completion(self, messages: List[Dict], model: str = None, **kwargs) -> Dict:
        """Generate chat completion using OpenAI's chat API."""
        if not model:
            model = self.get_default_model()
        
        # Validate parameters
        validated_params = self.validate_parameters(**kwargs)
        
        # Prepare request data
        request_data = {
            'model': model,
            'messages': messages,
            **validated_params
        }
        
        # Add provider-specific configuration
        provider = self.get_active_provider()
        if provider.provider_specific_config:
            try:
                config = json.loads(provider.provider_specific_config)
                if 'organization_id' in config:
                    request_data['organization'] = config['organization_id']
            except json.JSONDecodeError:
                _logger.error(f"Invalid provider config for OpenAI: {provider.provider_specific_config}")
        
        try:
            # Make API request
            headers = {
                'Authorization': f'Bearer {self.get_api_key()}',
                'Content-Type': 'application/json',
            }
            
            response = requests.post(
                f"{self.get_base_url()}/chat/completions",
                headers=headers,
                json=request_data,
                timeout=30
            )
            
            # Handle rate limits
            self.handle_rate_limits(response)
            
            if response.status_code == 200:
                response_data = response.json()
                
                # Log successful request
                self.log_request(request_data, response_data, 'success')
                
                return response_data
            else:
                error_data = response.json() if response.content else {}
                error_message = error_data.get('error', {}).get('message', f'HTTP {response.status_code}')
                
                # Log failed request
                self.log_request(request_data, error_data, 'error', error_message)
                
                raise UserError(_('OpenAI API error: %s') % error_message)
                
        except requests.exceptions.RequestException as e:
            error_message = f"Network error: {str(e)}"
            self.log_request(request_data, {}, 'error', error_message)
            raise UserError(_('Network error: %s') % str(e))
        except Exception as e:
            error_message = f"Unexpected error: {str(e)}"
            self.log_request(request_data, {}, 'error', error_message)
            raise UserError(_('Unexpected error: %s') % str(e))
    
    def get_embeddings(self, text: str, model: str = None) -> List[float]:
        """Get embeddings using OpenAI's embedding API."""
        if not model:
            model = 'text-embedding-ada-002'  # Default embedding model
        
        request_data = {
            'model': model,
            'input': text,
        }
        
        try:
            # Make API request
            headers = {
                'Authorization': f'Bearer {self.get_api_key()}',
                'Content-Type': 'application/json',
            }
            
            response = requests.post(
                f"{self.get_base_url()}/embeddings",
                headers=headers,
                json=request_data,
                timeout=30
            )
            
            # Handle rate limits
            self.handle_rate_limits(response)
            
            if response.status_code == 200:
                response_data = response.json()
                embeddings = response_data['data'][0]['embedding']
                
                # Log successful request
                self.log_request(request_data, response_data, 'success')
                
                return embeddings
            else:
                error_data = response.json() if response.content else {}
                error_message = error_data.get('error', {}).get('message', f'HTTP {response.status_code}')
                
                # Log failed request
                self.log_request(request_data, error_data, 'error', error_message)
                
                raise UserError(_('OpenAI API error: %s') % error_message)
                
        except requests.exceptions.RequestException as e:
            error_message = f"Network error: {str(e)}"
            self.log_request(request_data, {}, 'error', error_message)
            raise UserError(_('Network error: %s') % str(e))
        except Exception as e:
            error_message = f"Unexpected error: {str(e)}"
            self.log_request(request_data, {}, 'error', error_message)
            raise UserError(_('Unexpected error: %s') % str(e))
    
    def stream_response(self, prompt: str, model: str = None, **kwargs):
        """Stream response from OpenAI."""
        if not model:
            model = self.get_default_model()
        
        # Validate parameters
        validated_params = self.validate_parameters(**kwargs)
        validated_params['stream'] = True
        
        # Prepare request data
        request_data = {
            'model': model,
            'prompt': prompt,
            **validated_params
        }
        
        try:
            # Make streaming API request
            headers = {
                'Authorization': f'Bearer {self.get_api_key()}',
                'Content-Type': 'application/json',
            }
            
            response = requests.post(
                f"{self.get_base_url()}/completions",
                headers=headers,
                json=request_data,
                timeout=30,
                stream=True
            )
            
            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        if line.startswith('data: '):
                            data = line[6:]  # Remove 'data: ' prefix
                            if data == '[DONE]':
                                break
                            try:
                                chunk = json.loads(data)
                                if 'choices' in chunk and chunk['choices']:
                                    text = chunk['choices'][0].get('text', '')
                                    if text:
                                        yield text
                            except json.JSONDecodeError:
                                continue
            else:
                error_data = response.json() if response.content else {}
                error_message = error_data.get('error', {}).get('message', f'HTTP {response.status_code}')
                raise UserError(_('OpenAI API error: %s') % error_message)
                
        except requests.exceptions.RequestException as e:
            raise UserError(_('Network error: %s') % str(e))
        except Exception as e:
            raise UserError(_('Unexpected error: %s') % str(e))
    
    def call_function(self, function_name: str, arguments: Dict) -> Any:
        """Call a function using OpenAI's function calling feature."""
        # This would be implemented with the function calling framework
        # For now, return a placeholder
        return f"Function {function_name} called with arguments: {arguments}"
    
    def get_available_functions(self) -> List[Dict]:
        """Get list of available functions for OpenAI."""
        # This would return the registered function schemas
        return [] 