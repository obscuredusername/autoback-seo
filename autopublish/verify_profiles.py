import requests
import json

BASE_URL = 'http://localhost:8000'

def test_profile_flow():
    # 1. Create a user
    email = "testprofile@example.com"
    password = "password123"
    
    # Try to login first to get session
    session = requests.Session()
    login_response = session.post(f"{BASE_URL}/user/login/", json={
        "email": email,
        "password": password
    })
    
    if login_response.status_code != 200:
        # If login fails, try to create user
        print("Creating user...")
        create_response = requests.post(f"{BASE_URL}/user/create/", json={
            "email": email,
            "password": password
        })
        print(f"Create user response: {create_response.status_code} {create_response.text}")
        
        # Login again
        login_response = session.post(f"{BASE_URL}/user/login/", json={
            "email": email,
            "password": password
        })
    
    print(f"Login response: {login_response.status_code} {login_response.text}")
    
    if login_response.status_code != 200:
        print("Failed to login")
        return

    # 2. Create a profile
    print("\nCreating profile...")
    profile_data = {
        "name": "My Tech Blog",
        "language": "en",
        "region": "us",
        "domain_link": "https://techblog.com"
    }
    create_profile_response = session.post(f"{BASE_URL}/user/profiles/", json=profile_data)
    print(f"Create profile response: {create_profile_response.status_code} {create_profile_response.text}")
    
    if create_profile_response.status_code != 201:
        print("Failed to create profile")
        return
        
    profile_id = create_profile_response.json()['profile']['id']
    
    # 3. List profiles
    print("\nListing profiles...")
    list_response = session.get(f"{BASE_URL}/user/profiles/")
    print(f"List profiles response: {list_response.status_code} {list_response.text}")
    
    # 4. Get profile detail
    print(f"\nGetting profile {profile_id}...")
    detail_response = session.get(f"{BASE_URL}/user/profiles/{profile_id}/")
    print(f"Get detail response: {detail_response.status_code} {detail_response.text}")
    
    # 5. Update profile
    print(f"\nUpdating profile {profile_id}...")
    update_data = {"name": "Updated Tech Blog"}
    update_response = session.put(f"{BASE_URL}/user/profiles/{profile_id}/", json=update_data)
    print(f"Update response: {update_response.status_code} {update_response.text}")
    
    # 6. Delete profile
    print(f"\nDeleting profile {profile_id}...")
    delete_response = session.delete(f"{BASE_URL}/user/profiles/{profile_id}/")
    print(f"Delete response: {delete_response.status_code} {delete_response.text}")
    
    # 7. Verify deletion
    print(f"\nVerifying deletion...")
    detail_response_after_delete = session.get(f"{BASE_URL}/user/profiles/{profile_id}/")
    print(f"Get detail after delete response: {detail_response_after_delete.status_code} {detail_response_after_delete.text}")

if __name__ == "__main__":
    test_profile_flow()
