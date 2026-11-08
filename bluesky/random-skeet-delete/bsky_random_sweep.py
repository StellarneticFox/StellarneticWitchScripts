import json
import random
import sys
from pathlib import Path
from atproto import Client, models

CONFIG_FILE = Path(__file__).parent / "bsky_random_sweep.appsettings.local.json"

def load_config(config_path: Path) -> dict:
    """Load handle, app password, and batch size from a local JSON file."""
    if not config_path.exists():
        print(f"Error: Config file not found at '{config_path}'.")
        print("Please create the file with 'bsky_handle' and 'bsky_app_password' keys.")
        sys.exit(1)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON in '{config_path}': {e}")
        sys.exit(1)

    required_keys = ["bsky_handle", "bsky_app_password"]
    missing = [key for key in required_keys if not config.get(key)]
    if missing:
        print(f"Error: Missing required config key(s) in '{config_path}': {', '.join(missing)}")
        sys.exit(1)

    return config

def get_all_posts(client: Client, handle: str):
    """Paginate and fetch all post records from the user's repository."""
    posts = []
    cursor = None
    
    print("Fetching post history from your PDS...")
    while True:
        response = client.com.atproto.repo.list_records(
            models.ComAtprotoRepoListRecords.Params(
                repo=handle,
                collection="app.bsky.feed.post",
                limit=100,
                cursor=cursor
            )
        )
        posts.extend(response.records)
        cursor = response.cursor
        if not cursor:
            break
            
    return posts

def main():
    config = load_config(CONFIG_FILE)
    handle = config["bsky_handle"]
    app_password = config["bsky_app_password"]
    batch_size = config.get("batch_size", 5)

    client = Client()
    try:
        client.login(handle, app_password)
        print(f"Logged in as {handle}")
    except Exception as e:
        print(f"Authentication failed: {e}")
        sys.exit(1)

    all_posts = get_all_posts(client, handle)
    total_posts = len(all_posts)

    if total_posts == 0:
        print("No posts found in your account.")
        return

    print(f"Total posts retrieved: {total_posts}")

    sample_count = min(batch_size, total_posts)
    sampled_posts = random.sample(all_posts, sample_count)

    print("\n" + "=" * 60)
    print(f" RANDOM SELECTION ({sample_count} POSTS)")
    print("=" * 60 + "\n")

    posts_to_delete = []

    for idx, record in enumerate(sampled_posts, 1):
        rkey = record.uri.split('/')[-1]
        post_text = getattr(record.value, 'text', '[No text/Media post]')
        created_at = getattr(record.value, 'created_at', 'Unknown date')
        post_url = f"https://bsky.app/profile/{handle}/post/{rkey}"

        print(f"[{idx}/{sample_count}] Date: {created_at}")
        print(f"    URL:  {post_url}")
        print(f"    Text: {post_text.strip()}\n")

        choice = input(f"Delete post #{idx}? [y/N/q] (y=delete, N=skip, q=quit): ").strip().lower()
        if choice == 'q':
            print("Aborting remaining prompt.")
            break
        elif choice == 'y':
            posts_to_delete.append((rkey, record.uri))

    if not posts_to_delete:
        print("\nNo posts marked for deletion. Exiting.")
        return

    print(f"\nTargeting {len(posts_to_delete)} post(s) for deletion.")
    confirm = input("Confirm permanent deletion? Write 'DELETE' to confirm: ").strip()

    if confirm == "DELETE":
        for rkey, uri in posts_to_delete:
            try:
                client.com.atproto.repo.delete_record(
                    models.ComAtprotoRepoDeleteRecord.Data(
                        repo=client.me.did,
                        collection="app.bsky.feed.post",
                        rkey=rkey
                    )
                )
                print(f"Successfully deleted: {rkey}")
            except Exception as e:
                print(f"Failed to delete {rkey}: {e}")
        print("\nBatch sweep complete.")
    else:
        print("\nDeletion cancelled by user.")

if __name__ == "__main__":
    main()