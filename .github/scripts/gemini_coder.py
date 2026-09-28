import os
import re
from google import genai
from github import Github

# Environment variables
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
ISSUE_BODY = os.getenv("ISSUE_BODY", "")
REPO_NAME = os.getenv("GITHUB_REPOSITORY")

def process_issue():
    # প্রম্পট থেকে ফাইল পাথ এবং নির্দেশনা বের করা (কমান্ড Format: /refactor main.py Add try-catch)
    match = re.match(r'/refactor\s+(\S+)\s+(.+)', ISSUE_BODY, re.DOTALL)
    if not match:
        print("Invalid command format. Use: /refactor <file_path> <instructions>")
        return

    file_path, prompt = match.groups()

    # Github API কানেক্ট করা
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(REPO_NAME)

    try:
        content_file = repo.get_contents(file_path)
        file_content = content_file.decoded_content.decode("utf-8")
    except Exception as e:
        print(f"File not found: {file_path}")
        return

    # Gemini API কল করা
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    full_prompt = f"""
    You are an expert software developer. Refactor/modify the code based on instructions.
    Return ONLY the raw updated code. Do NOT add any explanations, introductory text, or markdown code blocks (no ```).

    File Path: {file_path}
    Original Code:
    {file_content}

    Instructions: {prompt}
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=full_prompt,
    )
    
    new_code = response.text.strip()

    # যদি মডেল ভুল করে markdown backticks দিয়ে দেয় তবে তা মুছে ফেলা
    if new_code.startswith("```"):
        new_code = re.sub(r'^```[a-zA-Z]*\n', '', new_code)
        new_code = re.sub(r'\n```$', '', new_code)

    # Repository-তে ফাইল আপডেট করা
    repo.update_file(
        path=file_path,
        message=f"Refactored {file_path} via Gemini AI",
        content=new_code,
        sha=content_file.sha,
        branch="main"
    )
    print(f"Successfully updated {file_path}")

if __name__ == "__main__":
    process_issue()
