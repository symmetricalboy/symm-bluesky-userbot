#!/usr/bin/env python3
"""
Verify deployment configuration and dependencies
"""

import sys
import os
import importlib.util

def check_python_version():
    """Check if Python version is compatible"""
    version = sys.version_info
    print(f"Python version: {version.major}.{version.minor}.{version.micro}")
    
    if version.major != 3 or version.minor < 11:
        print("❌ Warning: Python 3.11+ recommended for deployment")
        return False
    else:
        print("✅ Python version is compatible")
        return True

def check_required_modules():
    """Check if all required modules can be imported"""
    required_modules = [
        'atproto',
        'dotenv',
        'psycopg2',
        'psycopg',
        'httpx',
        'pydantic',
        'cbor2',
        'websockets',
        'psutil',
        'colorama'
    ]
    
    missing_modules = []
    for module in required_modules:
        try:
            if importlib.util.find_spec(module) is None:
                missing_modules.append(module)
            else:
                print(f"✅ {module} - available")
        except ImportError:
            missing_modules.append(module)
            print(f"❌ {module} - missing")
    
    if missing_modules:
        print(f"\n❌ Missing modules: {', '.join(missing_modules)}")
        print("Run: pip install -r requirements.txt")
        return False
    else:
        print("\n✅ All required modules are available")
        return True

def check_config_files():
    """Check if deployment config files exist"""
    files_to_check = [
        'railway.toml',
        'Procfile', 
        'requirements.txt',
        'runtime.txt',
        'main.py'
    ]
    
    missing_files = []
    for file in files_to_check:
        if os.path.exists(file):
            print(f"✅ {file} - exists")
        else:
            missing_files.append(file)
            print(f"❌ {file} - missing")
    
    if missing_files:
        print(f"\n❌ Missing config files: {', '.join(missing_files)}")
        return False
    else:
        print("\n✅ All config files present")
        return True

def check_environment_variables():
    """Check if required environment variables are set"""
    required_env_vars = [
        'PRIMARY_BLUESKY_HANDLE',
        'PRIMARY_BLUESKY_PASSWORD'
    ]
    
    missing_vars = []
    for var in required_env_vars:
        if os.getenv(var):
            print(f"✅ {var} - set")
        else:
            missing_vars.append(var)
            print(f"❌ {var} - not set")
    
    if missing_vars:
        print(f"\n❌ Missing environment variables: {', '.join(missing_vars)}")
        print("Set these in your Railway dashboard or .env file")
        return False
    else:
        print("\n✅ Required environment variables are set")
        return True

def main():
    print("🔍 Verifying deployment configuration...\n")
    
    checks = [
        ("Python Version", check_python_version),
        ("Required Modules", check_required_modules), 
        ("Config Files", check_config_files),
        ("Environment Variables", check_environment_variables)
    ]
    
    all_passed = True
    for check_name, check_func in checks:
        print(f"\n--- {check_name} ---")
        if not check_func():
            all_passed = False
    
    print("\n" + "="*50)
    if all_passed:
        print("🎉 All deployment checks passed!")
        print("Your application should deploy successfully to Railway.")
    else:
        print("❌ Some deployment checks failed.")
        print("Please fix the issues above before deploying.")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main()) 