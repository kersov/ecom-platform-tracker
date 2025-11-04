import json

# The file to read from and write back to
filename = 'sites.json'

unique_stores = []
seen_names = set()
seen_urls = set()

try:
    # --- 1. Read the file first ---
    # We must read the entire file into memory before we can write to it
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            stores = json.load(f)
        print(f"Reading from '{filename}'...")
    except FileNotFoundError:
        print(f"Error: The file '{filename}' was not found.")
        print("Please make sure the file exists in the same directory.")
        exit()
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{filename}'. Please check the file content.")
        exit()

    
    # --- 2. Process the data ---
    for store in stores:
        name = store.get('name')
        url = store.get('url')

        if not name or not url:
            continue

        norm_name = name.lower().strip()
        norm_url = url.lower().strip().replace('www.', '').rstrip('/')

        if norm_name not in seen_names and norm_url not in seen_urls:
            unique_stores.append(store)
            seen_names.add(norm_name)
            seen_urls.add(norm_url)

    removed_count = len(stores) - len(unique_stores)

    # --- 3. Write the unique data back to the *same* file ---
    # Using 'w' mode will overwrite the file's contents
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(unique_stores, f, indent=4)

    print(f"\nSuccessfully processed {len(stores)} entries.")
    if removed_count > 0:
        print(f"Removed {removed_count} duplicates.")
        print(f"Saved {len(unique_stores)} unique stores back to '{filename}'.")
    else:
        print(f"No duplicates found. '{filename}' remains unchanged in content.")

except Exception as e:
    print(f"An unexpected error occurred: {e}")