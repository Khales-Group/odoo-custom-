from odoo import http
from odoo.http import request, Response
import json
import logging
from werkzeug.exceptions import BadRequest, Unauthorized
from typing import Dict, Any

_logger = logging.getLogger(__name__)


class LLMAPIController(http.Controller):
    """Controller for LLM API endpoints."""
    
    @http.route('/ai_automation/llm/generate', type='json', auth='user', methods=['POST'])
    def generate_text(self, **kwargs):
        """Generate text using the configured LLM provider."""
        try:
            # Validate required parameters
            prompt = kwargs.get('prompt')
            if not prompt:
                raise BadRequest('Prompt is required')
            
            provider_code = kwargs.get('provider', 'openai')
            model = kwargs.get('model')
            
            # Get the appropriate service
            service_model = f'llm.{provider_code}.service'
            service = request.env[service_model]
            
            # Generate text
            result = service.generate_text(
                prompt=prompt,
                model=model,
                **{k: v for k, v in kwargs.items() if k not in ['prompt', 'provider', 'model']}
            )
            
            return {
                'success': True,
                'result': result,
                'provider': provider_code,
                'model': model or service.get_default_model()
            }
            
        except Exception as e:
            _logger.error(f"Error in generate_text: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @http.route('/ai_automation/llm/chat', type='json', auth='user', methods=['POST'])
    def chat_completion(self, **kwargs):
        """Generate chat completion using the configured LLM provider."""
        try:
            # Validate required parameters
            messages = kwargs.get('messages')
            if not messages or not isinstance(messages, list):
                raise BadRequest('Messages list is required')
            
            provider_code = kwargs.get('provider', 'openai')
            model = kwargs.get('model')
            
            # Get the appropriate service
            service_model = f'llm.{provider_code}.service'
            service = request.env[service_model]
            
            # Generate chat completion
            result = service.chat_completion(
                messages=messages,
                model=model,
                **{k: v for k, v in kwargs.items() if k not in ['messages', 'provider', 'model']}
            )
            
            return {
                'success': True,
                'result': result,
                'provider': provider_code,
                'model': model or service.get_default_model()
            }
            
        except Exception as e:
            _logger.error(f"Error in chat_completion: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @http.route('/ai_automation/llm/embeddings', type='json', auth='user', methods=['POST'])
    def get_embeddings(self, **kwargs):
        """Get embeddings for the given text."""
        try:
            # Validate required parameters
            text = kwargs.get('text')
            if not text:
                raise BadRequest('Text is required')
            
            provider_code = kwargs.get('provider', 'openai')
            model = kwargs.get('model')
            
            # Get the appropriate service
            service_model = f'llm.{provider_code}.service'
            service = request.env[service_model]
            
            # Get embeddings
            result = service.get_embeddings(
                text=text,
                model=model
            )
            
            return {
                'success': True,
                'result': result,
                'provider': provider_code,
                'model': model or service.get_default_model()
            }
            
        except Exception as e:
            _logger.error(f"Error in get_embeddings: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @http.route('/ai_automation/llm/stream', type='http', auth='user', methods=['POST'])
    def stream_response(self, **kwargs):
        """Stream response from the LLM provider."""
        try:
            # Get request data
            data = request.jsonrequest
            if not data:
                raise BadRequest('Request data is required')
            
            prompt = data.get('prompt')
            if not prompt:
                raise BadRequest('Prompt is required')
            
            provider_code = data.get('provider', 'openai')
            model = data.get('model')
            
            # Get the appropriate service
            service_model = f'llm.{provider_code}.service'
            service = request.env[service_model]
            
            # Set up streaming response
            def generate():
                try:
                    for chunk in service.stream_response(
                        prompt=prompt,
                        model=model,
                        **{k: v for k, v in data.items() if k not in ['prompt', 'provider', 'model']}
                    ):
                        yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                    yield "data: [DONE]\n\n"
                except Exception as e:
                    error_data = json.dumps({'error': str(e)})
                    yield f"data: {error_data}\n\n"
            
            return Response(
                generate(),
                mimetype='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'Connection': 'keep-alive',
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Headers': 'Cache-Control'
                }
            )
            
        except Exception as e:
            _logger.error(f"Error in stream_response: {str(e)}")
            return Response(
                f"data: {json.dumps({'error': str(e)})}\n\n",
                mimetype='text/event-stream'
            )
    
    @http.route('/ai_automation/llm/providers', type='json', auth='user', methods=['GET'])
    def get_providers(self):
        """Get list of available LLM providers."""
        try:
            providers = request.env['llm.provider'].search([('is_active', '=', True)])
            
            result = []
            for provider in providers:
                result.append({
                    'id': provider.id,
                    'name': provider.name,
                    'code': provider.code,
                    'default_model': provider.default_model_id.model_code if provider.default_model_id else None,
                    'api_base_url': provider.api_base_url,
                })
            
            return {
                'success': True,
                'providers': result
            }
            
        except Exception as e:
            _logger.error(f"Error in get_providers: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @http.route('/ai_automation/llm/models', type='json', auth='user', methods=['GET'])
    def get_models(self, provider_code=None):
        """Get list of available models for a provider."""
        try:
            domain = [('is_active', '=', True)]
            if provider_code:
                domain.append(('provider_type', '=', provider_code))
            
            models = request.env['llm.provider.model'].search(domain)
            
            result = []
            for model in models:
                result.append({
                    'id': model.id,
                    'name': model.name,
                    'model_code': model.model_code,
                    'provider_type': model.provider_type,
                    'supports_chat': model.supports_chat,
                    'supports_text_generation': model.supports_text_generation,
                    'supports_embeddings': model.supports_embeddings,
                    'supports_streaming': model.supports_streaming,
                    'supports_function_calling': model.supports_function_calling,
                    'max_tokens': model.max_tokens,
                    'context_length': model.context_length,
                })
            
            return {
                'success': True,
                'models': result
            }
            
        except Exception as e:
            _logger.error(f"Error in get_models: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @http.route('/ai_automation/llm/test_connection', type='json', auth='user', methods=['POST'])
    def test_connection(self, **kwargs):
        """Test connection to a specific LLM provider."""
        try:
            provider_code = kwargs.get('provider', 'openai')
            
            # Get the appropriate service
            service_model = f'llm.{provider_code}.service'
            service = request.env[service_model]
            
            # Test connection
            success = service.test_connection()
            
            return {
                'success': True,
                'connection_successful': success,
                'provider': provider_code
            }
            
        except Exception as e:
            _logger.error(f"Error in test_connection: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @http.route('/ai_automation/llm/usage_stats', type='json', auth='user', methods=['GET'])
    def get_usage_statistics(self, **kwargs):
        """Get usage statistics for monitoring."""
        try:
            provider_id = kwargs.get('provider_id')
            user_id = kwargs.get('user_id')
            date_from = kwargs.get('date_from')
            date_to = kwargs.get('date_to')
            
            stats = request.env['llm.request.log'].get_usage_statistics(
                provider_id=provider_id,
                user_id=user_id,
                date_from=date_from,
                date_to=date_to
            )
            
            return {
                'success': True,
                'statistics': stats
            }
            
        except Exception as e:
            _logger.error(f"Error in get_usage_statistics: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @http.route('/ai_automation/llm/function_call', type='json', auth='user', methods=['POST'])
    def call_function(self, **kwargs):
        """Call a registered function/tool."""
        try:
            function_name = kwargs.get('function_name')
            arguments = kwargs.get('arguments', {})
            provider_code = kwargs.get('provider', 'openai')
            
            if not function_name:
                raise BadRequest('Function name is required')
            
            # Get the appropriate service
            service_model = f'llm.{provider_code}.service'
            service = request.env[service_model]
            
            # Call function
            result = service.call_function(
                function_name=function_name,
                arguments=arguments
            )
            
            return {
                'success': True,
                'result': result,
                'function_name': function_name,
                'provider': provider_code
            }
            
        except Exception as e:
            _logger.error(f"Error in call_function: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @http.route('/ai_automation/llm/available_functions', type='json', auth='user', methods=['GET'])
    def get_available_functions(self, **kwargs):
        """Get list of available functions/tools."""
        try:
            provider_code = kwargs.get('provider', 'openai')
            
            # Get the appropriate service
            service_model = f'llm.{provider_code}.service'
            service = request.env[service_model]
            
            # Get available functions
            functions = service.get_available_functions()
            
            return {
                'success': True,
                'functions': functions,
                'provider': provider_code
            }
            
        except Exception as e:
            _logger.error(f"Error in get_available_functions: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            } 