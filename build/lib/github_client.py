import json
import base64


async def get_current_html(env):
    """Fetch the current index.html from the GitHub website repository.

    Returns (html_content, file_sha) or (None, None) on failure.
    """
    url = (
        f"https://api.github.com/repos/{env.github_repo_owner}/"
        f"{env.github_repo_name}/contents/{env.github_file_path}"
        f"?ref={env.github_branch}"
    )
    headers = {
        "Authorization": f"token {env.github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    response = await env.http_request("GET", url, headers=headers)

    if response["status"] != 200:
        return None, None

    data = json.loads(response["text"])
    content = base64.b64decode(data["content"]).decode("utf-8")
    sha = data["sha"]
    return content, sha


async def update_html(env, new_html, commit_message):
    """Push updated index.html to the GitHub website repository.

    Returns (success: bool, message: str).
    """
    # Get the current file SHA (required by GitHub API for updates)
    _, sha = await get_current_html(env)
    if sha is None:
        return False, "Could not fetch current file from GitHub."

    url = (
        f"https://api.github.com/repos/{env.github_repo_owner}/"
        f"{env.github_repo_name}/contents/{env.github_file_path}"
    )
    headers = {
        "Authorization": f"token {env.github_token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }
    body = {
        "message": commit_message,
        "content": base64.b64encode(new_html.encode("utf-8")).decode("utf-8"),
        "sha": sha,
        "branch": env.github_branch,
    }

    response = await env.http_request("PUT", url, headers=headers, body=body)

    if response["status"] in (200, 201):
        return True, "Successfully updated."
    else:
        return False, f"GitHub API error (status {response['status']})."
