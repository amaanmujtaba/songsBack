from flask import Flask, request, send_file, jsonify
from googleapiclient.discovery import build
import os
import yt_dlp as youtube_dl  # Use yt-dlp instead of youtube-dl
import requests
import base64
import re
import logging
from flask_cors import CORS, cross_origin
import firebase_admin
from firebase_admin import credentials, storage
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Access environment variables
API_KEY = os.getenv('API_KEY')
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')

# Path to the service account key
cred = credentials.Certificate('./serviceAccountKey.json')
firebase_admin.initialize_app(cred, {
    'storageBucket': 'songs-6d89c.appspot.com'
})

def upload_test_file():
    bucket = storage.bucket()
    blob = bucket.blob('test_upload.txt')
    blob.upload_from_string('This is a test file.')
    print(f'File uploaded to {blob.public_url}')





app = Flask(__name__)
cors = CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'




#firebase bucket
bucket = storage.bucket()  # Define bucket here

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_spotify_token():
    auth_url = 'https://accounts.spotify.com/api/token'
    auth_headers = {
        'Authorization': 'Basic ' + base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    }
    auth_data = {
        'grant_type': 'client_credentials'
    }
    
    response = requests.post(auth_url, headers=auth_headers, data=auth_data)
    response_data = response.json()
    
    if response.status_code != 200:
        logger.error("Failed to get Spotify token")
        return None
    
    return response_data['access_token']

def extract_playlist_id(playlist_link):
    match = re.search(r'playlist/([a-zA-Z0-9]+)', playlist_link)
    if match:
        return match.group(1)
    return None

def get_playlist_tracks(playlist_id, token):
    playlist_url = f'https://api.spotify.com/v1/playlists/{playlist_id}/tracks'
    headers = {
        'Authorization': f'Bearer {token}'
    }
    
    response = requests.get(playlist_url, headers=headers)
    if response.status_code != 200:
        logger.error("Failed to get playlist tracks")
        return []
    
    tracks_data = response.json()
    tracks = []
    for item in tracks_data['items']:
        try:
            track = item['track']
            if(len(tracks) == 20):
                return tracks
            if track:  # Ensure track is not None
                track_info = {
                    'title': track['name'],
                    'artist': track['artists'][0]['name']
                }
                tracks.append(track_info)
        except:
            continue
    
    return tracks

# Create a service object for interacting with the YouTube Data API
youtube = build('youtube', 'v3', developerKey=API_KEY)

def search_videos(query):
    search_response = youtube.search().list(
        q=query,
        part='id,snippet',
        maxResults=1,
        type='video',  # specify that we're searching for videos
        videoCategoryId='10'  # filter by the "Music" category
    ).execute()
    
    video_ids = []
    for item in search_response['items']:
        if item['id']['kind'] == 'youtube#video':
            video_ids.append({
                'id': item['id']['videoId'],
                'title': item['snippet']['title']
            })
    
    return video_ids
def sanitize_file_path(file_path):
    # Define a list of characters to remove or replace
    bad_chars = ['#', '$', '%', '&', '*', '{', '}', '\\', ':', '<', '>', '?', '/', '+', '|', '"', '\'']

    # Replace each bad character with an empty string
    for char in bad_chars:
        file_path = file_path.replace(char, '')

    return file_path

def download_audio(url, title):
    # output_directory = r"C:\Users\amaan\Songs Project\songs"
    # output_path = os.path.join(output_directory, f"{title}.mp3")
    title = sanitize_file_path(title)
    
    options = {
        'format': 'bestaudio/best',
        'extractaudio': True,  # only keep the audio
        'audioformat': 'mp3',  # convert to mp3
        'outtmpl': f'{title}.mp3',  # save to file
    }
    # if os.path.exists(output_path):
    #     logger.info(f"File already exists: {output_path}")
    #     return
    
    # Use yt-dlp to download the audio
    with youtube_dl.YoutubeDL(options) as ydl:
        ydl.download([url])
    
    # Upload the downloaded file to Firebase Storage
    file_path = f'{title}.mp3'
    file_path = sanitize_file_path(file_path) 

    
    download_url = upload_to_firebase(file_path)
    return download_url




def upload_to_firebase(file_path):
    file_path = sanitize_file_path(file_path) 
    blob = bucket.blob(os.path.basename(file_path))
    blob.upload_from_filename(file_path)
    os.remove(file_path)
    logger.info(f"Uploaded {file_path} to Firebase")
    
    # Generate and return the download URL
    download_url = blob.generate_signed_url(
        expiration=datetime.utcnow() + timedelta(hours=3),  # URL valid for 1 hour
        version='v4'
    )
    return download_url

@app.route("/")
def home():
    return "<h1>Welcome to your Flask application!</h1>"

# Route for seeing a data
@app.route('/data')
def get_time():
 
    # Returning an api for showing in  reactjs
    return {
        "string": "hi"
        }

@app.route('/download', methods=['POST'])
@cross_origin()
def download_playlist():
    data = request.get_json()
    download_links = []
    
    playlist_link = data.get('link')
    print(playlist_link)
    playlist_id = extract_playlist_id(playlist_link)
    print("id", playlist_id)
    if playlist_id:
        spotify_token = get_spotify_token()
        if spotify_token:
            tracks = get_playlist_tracks(playlist_id, spotify_token)
            # tracks = tracks[:20]
            for track in tracks:
                try:
                    query = f"{track['title']} - {track['artist']}"
                    videos = search_videos(query)
                    if videos:
                        video = videos[0]
                        video_link = f"https://www.youtube.com/watch?v={video['id']}"
                        download_url = download_audio(video_link, query)
                        download_links.append([track['title'],download_url])
                    else:
                        logger.warning(f"No videos found for {query}")
                except:
                    continue
        else:
            logger.error("Failed to get Spotify token.")
    else:
        logger.error("Failed to extract playlist ID from link.")
    print("Returned: download links: ", download_links)
    return jsonify({"message": "Download links generated", "links": download_links})




if __name__ == "__main__":
    print("server started")
    # upload_test_file()
    # for a single song    
    # query = f"Your song - Elton John"
    # videos = search_videos(query)
    # if videos:
    #     video = videos[0]
    #     video_link = f"https://www.youtube.com/watch?v={video['id']}"
    #     download_url = download_audio(video_link, query)
    #     print(download_url)
    # else:
    #     logger.warning(f"No videos found for {query}")
    
    #works for playlist?
    # download_links = []
    # playlist_link = 'https://open.spotify.com/playlist/7rQBG7jyRPKGKMHW6dBAMv?si=291e7f5e52cc4bd0'
    # playlist_id = extract_playlist_id(playlist_link)
    # if playlist_id:
    #     spotify_token = get_spotify_token()
    #     if spotify_token:
    #         tracks = get_playlist_tracks(playlist_id, spotify_token)
    #         for track in tracks:
    #             try:
    #                 query = f"{track['title']} - {track['artist']}"
    #                 videos = search_videos(query)
    #                 if videos:
    #                     video = videos[0]
    #                     video_link = f"https://www.youtube.com/watch?v={video['id']}"
    #                     download_url= download_audio(video_link, query)
    #                     download_links.append([track['title'], download_url])
    #                 else:
    #                     logger.warning(f"No videos found for {query}")
    #             except:
    #                 continue
    #     else:
    #         logger.error("Failed to get Spotify token.")
    # else:
    #     logger.error("Failed to extract playlist ID from link.")
    # for i in download_links:
    #     print(i)
    app.run(debug=True)
