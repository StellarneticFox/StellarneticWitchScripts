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
    handle = config["bsky_handle"].strip()
    app_password = config["bsky_app_password"].strip()
    batch_size = config.get("batch_size", 5)

    client = Client("https://northsky.social")  # Preferred PDS URL
    try:
        client.login(handle, app_password)
        print(f"Logged in as {handle}")
    except Exception as e:
        print(f"Authentication failed: {e}")
        sys.exit(1)

    raw_posts = get_all_posts(client, handle)
    total_posts = len(raw_posts)

    if total_posts == 0:
        print("No posts found in your account.")
        return

    print(f"Total posts retrieved: {total_posts}")

    # Pick up to batch_size posts at random
    sample_count = min(batch_size, total_posts)
    sampled_records = random.sample(raw_posts, sample_count)

    # Collect URIs for sample posts and any parent reply URIs
    sample_uris = [rec.uri for rec in sampled_records]
    parent_uris = []

    for record in sampled_records:
        reply_ref = getattr(record.value, 'reply', None)
        if reply_ref and hasattr(reply_ref, 'parent') and getattr(reply_ref.parent, 'uri', None):
            parent_uris.append(reply_ref.parent.uri)

    # Hydrate sample posts and parent posts in batch
    all_uris_to_fetch = list(set(sample_uris + parent_uris))
    post_views = {}
    
    if all_uris_to_fetch:
        try:
            hydrated_response = client.get_posts(all_uris_to_fetch)
            post_views = {pv.uri: pv for pv in hydrated_response.posts}
        except Exception as e:
            print(f"Warning: Failed to hydrate some post details: {e}")

    print("\n" + "=" * 70)
    print(f" RANDOM SELECTION ({sample_count} POSTS)")
    print("=" * 70 + "\n")

    posts_to_delete = []

    for idx, record in enumerate(sampled_records, 1):
        rkey = record.uri.split('/')[-1]
        post_view = post_views.get(record.uri)
        
        post_text = getattr(record.value, 'text', '[No text/Media post]')
        created_at = getattr(record.value, 'created_at', 'Unknown date')
        post_url = f"https://bsky.app/profile/{handle}/post/{rkey}"

        # Metrics
        likes = post_view.like_count if post_view and hasattr(post_view, 'like_count') else 0
        reposts = post_view.repost_count if post_view and hasattr(post_view, 'repost_count') else 0

        # Reply detection
        reply_ref = getattr(record.value, 'reply', None)
        is_reply = reply_ref is not None

        print(f"[{idx}/{sample_count}] Date:  {created_at}")
        print(f"    URL:   {post_url}")
        print(f"    Likes: ❤️ {likes}  |  Reposts: 🔁 {reposts}")

        if is_reply:
            parent_uri = reply_ref.parent.uri
            parent_view = post_views.get(parent_uri)

            if parent_view and hasattr(parent_view, 'author'):
                parent_handle = getattr(parent_view.author, 'handle', 'Unknown User')
                parent_text = getattr(parent_view.record, 'text', '[No text/Media]')
                parent_rkey = parent_uri.split('/')[-1]
                parent_url = f"https://bsky.app/profile/{parent_handle}/post/{parent_rkey}"
                
                print(f"    Type:  💬 REPLY to @{parent_handle}")
                print(f"           Parent URL:  {parent_url}")
                print(f"           Parent Text: {parent_text.strip()}")
            else:
                # Fallback if parent post deleted or unresolvable
                parent_rkey = parent_uri.split('/')[-1]
                parent_did_or_handle = parent_uri.split('/')[2]
                parent_url = f"https://bsky.app/profile/{parent_did_or_handle}/post/{parent_rkey}"
                print(f"    Type:  💬 REPLY to post: {parent_url}")
        else:
            print(f"    Type:  📝 Standalone Post")

        # Media / Image inspection on current post
        if post_view and hasattr(post_view, 'embed') and post_view.embed:
            embed = post_view.embed
            
            # Direct image attachments
            if hasattr(embed, 'images') and embed.images:
                print(f"    Media: 🖼️ {len(embed.images)} Image(s) Attached:")
                for img_idx, img in enumerate(embed.images, 1):
                    alt_str = f' | Alt: "{img.alt}"' if getattr(img, 'alt', None) else ""
                    full_url = getattr(img, 'fullsize', '[URL Unavailable]')
                    print(f"           - Image #{img_idx}: {full_url}{alt_str}")

            # External link card thumbnails
            elif hasattr(embed, 'external') and embed.external:
                thumb_str = f" [Thumb: {embed.external.thumb}]" if getattr(embed.external, 'thumb', None) else ""
                print(f"    Link:  🔗 {embed.external.uri}{thumb_str}")

        print(f"    Text:  {post_text.strip()}\n")

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