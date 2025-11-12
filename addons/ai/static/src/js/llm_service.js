/** @odoo-module **/

import { jsonrpc } from "@web/core/network/rpc";

/**
 * LLM Service for AI Automation Base
 * Provides methods to interact with LLM providers through the backend API
 */
export const LLMService = {
    /**
     * Generate text using the configured LLM provider
     * @param {string} prompt - The input prompt
     * @param {string} provider - Provider code (optional, defaults to 'openai')
     * @param {string} model - Model name (optional)
     * @param {Object} options - Additional options
     * @returns {Promise} Promise that resolves with the generated text
     */
    async generateText(prompt, provider = 'openai', model = null, options = {}) {
        return await jsonrpc('/ai_automation/llm/generate', {
            prompt: prompt,
            provider: provider,
            model: model,
            ...options
        });
    },

    /**
     * Generate chat completion using the configured LLM provider
     * @param {Array} messages - Array of message objects with role and content
     * @param {string} provider - Provider code (optional, defaults to 'openai')
     * @param {string} model - Model name (optional)
     * @param {Object} options - Additional options
     * @returns {Promise} Promise that resolves with the chat completion
     */
    async chatCompletion(messages, provider = 'openai', model = null, options = {}) {
        return await jsonrpc('/ai_automation/llm/chat', {
            messages: messages,
            provider: provider,
            model: model,
            ...options
        });
    },

    /**
     * Get embeddings for the given text
     * @param {string} text - Input text to embed
     * @param {string} provider - Provider code (optional, defaults to 'openai')
     * @param {string} model - Model name (optional)
     * @returns {Promise} Promise that resolves with the embeddings
     */
    async getEmbeddings(text, provider = 'openai', model = null) {
        return await jsonrpc('/ai_automation/llm/embeddings', {
            text: text,
            provider: provider,
            model: model
        });
    },

    /**
     * Stream response from the LLM provider
     * @param {string} prompt - The input prompt
     * @param {string} provider - Provider code (optional, defaults to 'openai')
     * @param {string} model - Model name (optional)
     * @param {Object} options - Additional options
     * @param {Function} onChunk - Callback function for each chunk
     * @param {Function} onComplete - Callback function when streaming is complete
     * @param {Function} onError - Callback function for errors
     */
    streamResponse(prompt, provider = 'openai', model = null, options = {}, onChunk, onComplete, onError) {
        const data = {
            prompt: prompt,
            provider: provider,
            model: model,
            ...options
        };

        fetch('/ai_automation/llm/stream', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            },
            body: JSON.stringify(data),
            credentials: 'same-origin'
        })
        .then(function (response) {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();

            function readStream() {
                return reader.read().then(function (result) {
                    if (result.done) {
                        if (onComplete) onComplete();
                        return;
                    }

                    const chunk = decoder.decode(result.value, {stream: true});
                    const lines = chunk.split('\n');

                    lines.forEach(function (line) {
                        if (line.startsWith('data: ')) {
                            const data = line.slice(6);
                            if (data === '[DONE]') {
                                if (onComplete) onComplete();
                                return;
                            }

                            try {
                                const parsed = JSON.parse(data);
                                if (parsed.chunk && onChunk) {
                                    onChunk(parsed.chunk);
                                } else if (parsed.error && onError) {
                                    onError(parsed.error);
                                }
                            } catch (e) {
                                // Ignore parsing errors for incomplete chunks
                            }
                        }
                    });

                    return readStream();
                });
            }

            return readStream();
        })
        .catch(function (error) {
            if (onError) onError(error.message);
        });
    },

    /**
     * Get available LLM providers
     * @returns {Promise} Promise that resolves with the list of providers
     */
    async getProviders() {
        return await jsonrpc('/ai_automation/llm/providers', {});
    },

    /**
     * Get available models for a provider
     * @param {string} providerCode - Provider code (optional)
     * @returns {Promise} Promise that resolves with the list of models
     */
    async getModels(providerCode = null) {
        return await jsonrpc('/ai_automation/llm/models', {
            provider_code: providerCode
        });
    },

    /**
     * Test connection to a specific LLM provider
     * @param {string} provider - Provider code
     * @returns {Promise} Promise that resolves with the test result
     */
    async testConnection(provider) {
        return await jsonrpc('/ai_automation/llm/test_connection', {
            provider: provider
        });
    },

    /**
     * Get usage statistics
     * @param {Object} filters - Optional filters (provider_id, user_id, date_from, date_to)
     * @returns {Promise} Promise that resolves with usage statistics
     */
    async getUsageStatistics(filters = {}) {
        return await jsonrpc('/ai_automation/llm/usage_stats', filters);
    },

    /**
     * Call a registered function/tool
     * @param {string} functionName - Name of the function to call
     * @param {Object} functionArgs - Arguments to pass to the function
     * @param {string} provider - Provider code (optional, defaults to 'openai')
     * @returns {Promise} Promise that resolves with the function result
     */
    async callFunction(functionName, functionArgs, provider = 'openai') {
        return await jsonrpc('/ai_automation/llm/function_call', {
            function_name: functionName,
            arguments: functionArgs,
            provider: provider
        });
    },

    /**
     * Get available functions/tools
     * @param {string} provider - Provider code (optional, defaults to 'openai')
     * @returns {Promise} Promise that resolves with the list of functions
     */
    async getAvailableFunctions(provider = 'openai') {
        return await jsonrpc('/ai_automation/llm/available_functions', {
            provider: provider
        });
    }
}; 