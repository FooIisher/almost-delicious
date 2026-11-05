"""Launch the prototype with a process-local OpenAI key (never saved to disk)."""
import getpass
import os
from pathlib import Path
import uvicorn

if __name__ == '__main__':
    os.chdir(Path(__file__).resolve().parent)
    if not any(os.environ.get(name, '').strip() for name in ('OPENAI_API_KEY', 'DEEPSEEK_API_KEY')):
        os.environ['OPENAI_API_KEY']=getpass.getpass('OpenAI API key (hidden, not saved): ').strip()
    if not any(os.environ.get(name, '').strip() for name in ('OPENAI_API_KEY', 'DEEPSEEK_API_KEY')):
        raise SystemExit('An OpenAI API key is required for intent analysis.')
    uvicorn.run('recipe_search_api:app',host='127.0.0.1',port=8002)
