import os
import requests
import json
import time

# Configuration
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") # Use the token provided in workflow
LLM_API_KEY = os.environ.get("LLM_API_KEY")
LLM_API_BASE = os.environ.get("LLM_API_BASE", "https://api.z.ai/api/paas/v4/")
LLM_MODEL = os.environ.get("LLM_MODEL", "glm-4.5-flash")
README_FILE = "profile/README.md"
DATA_FILE = "repo_data.json"

def fetch_github_repos(username):
    """Fetch all public repositories for a GitHub user."""
    repos = []
    page = 1
    headers = {
        "Accept": "application/vnd.github.v3+json"
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"

    while True:
        url = f"https://api.github.com/users/{username}/repos?per_page=100&page={page}"
        print(f"Fetching page {page} from GitHub...")
        try:
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                print(f"Failed to fetch repos: {response.status_code} {response.text}")
                break
            
            data = response.json()
            if not data:
                break
            
            repos.extend(data)
            page += 1
        except Exception as e:
            print(f"Error fetching github repos: {e}")
            break
            
    return repos

def get_readme_content(username, repo_name):
    """Fetch the README content for a repository."""
    url = f"https://api.github.com/repos/{username}/{repo_name}/readme"
    headers = {
        "Accept": "application/vnd.github.v3+json"
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"

    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if "content" in data:
                import base64
                content = base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
                return content[:2000] # Truncate to avoid token limits
    except Exception as e:
        print(f"Error fetching README for {repo_name}: {e}")
    
    return ""

def get_llm_description(repo_name, current_description, readme_content=""):
    """Generate a classification and description using LLM."""
    if not LLM_API_KEY:
        print("Skipping LLM: No API Key")
        return {"category": "Unclassified", "enhanced_description": current_description or ""}

    prompt = f"""
    Analyze the following repository:
    Name: {repo_name}
    Description: {current_description}
    README Content (excerpt):
    {readme_content}

    Provide a JSON response with two keys:
    1. "category": A short category name (e.g., "AI", "Tools", "Web", "System", "Learning", "Mobile").
    2. "enhanced_description": A polished, one-sentence description (in Chinese if the input is Chinese, else English).
    
    Return ONLY valid JSON.
    """

    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5
    }

    try:
        # Retry logic
        for _ in range(3):
            try:
                response = requests.post(f"{LLM_API_BASE}/chat/completions", headers=headers, json=data, timeout=30)
                if response.status_code == 200:
                    result = response.json()
                    content = result["choices"][0]["message"]["content"]
                    # Clean up potential markdown formatting
                    if "```json" in content:
                        content = content.split("```json")[1].split("```")[0].strip()
                    elif "```" in content:
                        content = content.split("```")[1].split("```")[0].strip()
                    
                    return json.loads(content)
                else:
                    print(f"LLM Error: {response.status_code}")
                    time.sleep(2)
            except requests.exceptions.Timeout:
                 print("LLM Request timed out")
                 time.sleep(2)
                 
    except Exception as e:
        print(f"LLM Call failed: {e}")
    
    return {"category": "Unclassified", "enhanced_description": current_description or ""}

def main():
    if not GITHUB_USERNAME:
        print("Error: GITHUB_USERNAME environment variable is not set.")
        # Try to infer from GITHUB_REPOSITORY if token is present, but manual set is safer
        return

    # Load cache
    cache = {}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                cache = json.load(f)
        except:
            print("Failed to load cache, starting fresh.")

    repos = fetch_github_repos(GITHUB_USERNAME)
    if not repos:
        print("No repositories found.")
        return

    print(f"Found {len(repos)} repositories. Processing...")
    
    current_time = time.strftime("%Y-%m-%d %H:%M:%S")

    categorized_repos = {}
    
    # Track used repos to clean up stale cache if needed (optional, keeping simple for now)
    
    updated_cache = False

    for repo in repos:
        name = repo.get("name")
        desc = repo.get("description")
        html_url = repo.get("html_url")
        
        # Check cache
        if name in cache and cache[name].get("description") == desc:
            # If description hasn't changed on GitHub, assume our LLM cache is still valid
            llm_data = cache[name]["llm_data"]
        else:
            # New or updated
            print(f"Analyzing new/updated repo: {name}")
            readme = get_readme_content(GITHUB_USERNAME, name)
            llm_data = get_llm_description(name, desc, readme)
            cache[name] = {
                "description": desc,
                "llm_data": llm_data,
                "last_updated": current_time
            }
            updated_cache = True
            time.sleep(1) # Rate limit protection

        cat = llm_data.get("category", "Unclassified")
        new_desc = llm_data.get("enhanced_description", desc)

        if cat not in categorized_repos:
            categorized_repos[cat] = []
            
        categorized_repos[cat].append({
            "name": name,
            "url": html_url,
            "description": new_desc
        })

    # Save cache
    if updated_cache:
        with open(DATA_FILE, "w") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)

    # Generate README content
    content = "# My Mirrored Repositories\n\n"
    content += f"Automatically mirrored from Gitcode and other sources. Last updated: {current_time}\n\n"
    
    # Sort categories
    sorted_cats = sorted(categorized_repos.keys())
    
    for category in sorted_cats:
        content += f"## {category}\n\n"
        content += "| Repository | Description |\n"
        content += "| ---------- | ----------- |\n"
        for item in categorized_repos[category]:
            desc_text = item['description'] if item['description'] else "-"
            content += f"| [{item['name']}]({item['url']}) | {desc_text} |\n"
        content += "\n"

    os.makedirs(os.path.dirname(README_FILE), exist_ok=True)
    with open(README_FILE, "w") as f:
        f.write(content)
    print("README.md updated successfully.")

if __name__ == "__main__":
    main()
