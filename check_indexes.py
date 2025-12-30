"""Script to check and create MongoDB indexes for optimal performance."""
import asyncio
from utils.database import MongoClient


async def check_and_create_indexes():
    """Check existing indexes and create missing ones."""
    mongo = MongoClient()

    print("=" * 60)
    print("CHECKING MONGODB INDEXES")
    print("=" * 60)

    # Check coc_accounts collection
    print("\n📊 Collection: coc_accounts")
    print("-" * 60)
    existing_indexes = await mongo.coc_accounts.list_indexes().to_list(length=None)
    print("Existing indexes:")
    for idx in existing_indexes:
        print(f"  ✓ {idx['name']}: {idx.get('key', {})}")

    # Create index on user_id if missing
    user_id_exists = any('user_id' in idx.get('key', {}) for idx in existing_indexes)
    if not user_id_exists:
        print("\n⚠️  Missing index on 'user_id', creating...")
        await mongo.coc_accounts.create_index("user_id")
        print("  ✅ Created index on 'user_id'")
    else:
        print("\n✅ Index on 'user_id' already exists")

    # Check server_db collection
    print("\n📊 Collection: server_db")
    print("-" * 60)
    existing_indexes = await mongo.server_db.list_indexes().to_list(length=None)
    print("Existing indexes:")
    for idx in existing_indexes:
        print(f"  ✓ {idx['name']}: {idx.get('key', {})}")

    # Create index on server if missing
    server_exists = any('server' in idx.get('key', {}) for idx in existing_indexes)
    if not server_exists:
        print("\n⚠️  Missing index on 'server', creating...")
        await mongo.server_db.create_index("server")
        print("  ✅ Created index on 'server'")
    else:
        print("\n✅ Index on 'server' already exists")

    # Check users collection
    print("\n📊 Collection: users")
    print("-" * 60)
    existing_indexes = await mongo.users.list_indexes().to_list(length=None)
    print("Existing indexes:")
    for idx in existing_indexes:
        print(f"  ✓ {idx['name']}: {idx.get('key', {})}")

    # Create index on user_id if missing
    user_id_exists = any('user_id' in idx.get('key', {}) for idx in existing_indexes)
    if not user_id_exists:
        print("\n⚠️  Missing index on 'user_id', creating...")
        await mongo.users.create_index("user_id")
        print("  ✅ Created index on 'user_id'")
    else:
        print("\n✅ Index on 'user_id' already exists")

    print("\n" + "=" * 60)
    print("✅ INDEX CHECK COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(check_and_create_indexes())
