#!/usr/bin/env python3
"""
Test script for AI Automation Base module installation.
Run this script to verify that the module is properly installed and configured.
"""

import sys
import os

def test_module_structure():
    """Test that all required files and directories exist."""
    print("Testing module structure...")
    
    required_files = [
        '__init__.py',
        '__manifest__.py',
        'README.md',
        'models/__init__.py',
        'models/llm_provider.py',
        'models/llm_api_key.py',
        'models/llm_provider_model.py',
        'models/llm_base_service.py',
        'models/llm_openai_service.py',
        'models/llm_gemini_service.py',
        'models/llm_claude_service.py',
        'models/llm_request_log.py',
        'controllers/__init__.py',
        'controllers/llm_api_controller.py',
        'views/llm_provider_views.xml',
        'views/llm_api_key_views.xml',
        'views/llm_provider_model_views.xml',
        'views/llm_request_log_views.xml',
        'views/ai_automation_base_menus.xml',
        'security/ai_automation_base_security.xml',
        'security/ir.model.access.csv',
        'data/default_providers.xml',
        'static/src/js/llm_service.js',
        'static/src/css/llm_interface.css',
    ]
    
    missing_files = []
    for file_path in required_files:
        if not os.path.exists(file_path):
            missing_files.append(file_path)
    
    if missing_files:
        print(f"❌ Missing files: {missing_files}")
        return False
    else:
        print("✅ All required files present")
        return True

def test_manifest():
    """Test that the manifest file is valid."""
    print("\nTesting manifest file...")
    
    try:
        with open('__manifest__.py', 'r') as f:
            content = f.read()
        
        # Basic validation
        if "'name': 'AI Automation Base'" in content:
            print("✅ Manifest file appears valid")
            return True
        else:
            print("❌ Manifest file validation failed")
            return False
    except Exception as e:
        print(f"❌ Error reading manifest file: {e}")
        return False

def test_python_syntax():
    """Test that Python files have valid syntax."""
    print("\nTesting Python syntax...")
    
    python_files = [
        '__init__.py',
        'models/__init__.py',
        'models/llm_provider.py',
        'models/llm_api_key.py',
        'models/llm_provider_model.py',
        'models/llm_base_service.py',
        'models/llm_openai_service.py',
        'models/llm_gemini_service.py',
        'models/llm_claude_service.py',
        'models/llm_request_log.py',
        'controllers/__init__.py',
        'controllers/llm_api_controller.py',
    ]
    
    syntax_errors = []
    for file_path in python_files:
        try:
            with open(file_path, 'r') as f:
                compile(f.read(), file_path, 'exec')
        except SyntaxError as e:
            syntax_errors.append(f"{file_path}: {e}")
    
    if syntax_errors:
        print(f"❌ Syntax errors found: {syntax_errors}")
        return False
    else:
        print("✅ All Python files have valid syntax")
        return True

def test_xml_syntax():
    """Test that XML files are well-formed."""
    print("\nTesting XML syntax...")
    
    xml_files = [
        'views/llm_provider_views.xml',
        'views/llm_api_key_views.xml',
        'views/llm_provider_model_views.xml',
        'views/llm_request_log_views.xml',
        'views/ai_automation_base_menus.xml',
        'security/ai_automation_base_security.xml',
        'data/default_providers.xml',
    ]
    
    try:
        import xml.etree.ElementTree as ET
        
        xml_errors = []
        for file_path in xml_files:
            try:
                ET.parse(file_path)
            except ET.ParseError as e:
                xml_errors.append(f"{file_path}: {e}")
        
        if xml_errors:
            print(f"❌ XML errors found: {xml_errors}")
            return False
        else:
            print("✅ All XML files are well-formed")
            return True
    except ImportError:
        print("⚠️  XML validation skipped (xml.etree.ElementTree not available)")
        return True

def main():
    """Run all tests."""
    print("AI Automation Base - Installation Test")
    print("=" * 50)
    
    # Change to the module directory
    module_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(module_dir)
    
    tests = [
        test_module_structure,
        test_manifest,
        test_python_syntax,
        test_xml_syntax,
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"❌ Test failed with exception: {e}")
            results.append(False)
    
    print("\n" + "=" * 50)
    print("Test Results Summary:")
    print("=" * 50)
    
    if all(results):
        print("🎉 All tests passed! The module appears to be properly installed.")
        print("\nNext steps:")
        print("1. Install the module in Odoo")
        print("2. Configure API keys for your LLM providers")
        print("3. Set up provider configurations")
        print("4. Assign users to appropriate AI groups")
        return 0
    else:
        print("❌ Some tests failed. Please check the errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 