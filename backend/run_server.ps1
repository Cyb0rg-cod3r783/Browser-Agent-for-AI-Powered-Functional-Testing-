# Change to the script's directory
Set-Location -Path $PSScriptRoot

# Activate the virtual environment
. .\venv2\Scripts\Activate.ps1

# Install dependencies from requirements.txt
pip install -r requirements.txt

# List installed packages to verify the environment
pip freeze

# Run the Uvicorn server
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload