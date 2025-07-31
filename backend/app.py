# backend/app.py

from flask import Flask, request, jsonify, session
from flask_cors import CORS
from supabase import create_client, Client
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing.image import img_to_array
import cv2
import numpy as np
import base64
import io
from PIL import Image
import os
from datetime import datetime
import jwt

app = Flask(__name__)
CORS(app, supports_credentials=True)
app.config['SECRET_KEY'] = 'your-secret-key-here'

# Supabase configuration
try:
    from config import SUPABASE_URL, SUPABASE_ANON_KEY
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
except ImportError:
    print("⚠️  Please create config.py with your Supabase credentials!")
    print("Check config.py file for instructions.")
    supabase = None

# Helper function to verify JWT token
def verify_token(token):
    try:
        # Verify with Supabase
        user = supabase.auth.get_user(token)
        return user.user if user.user else None
    except Exception as e:
        print(f"Token verification error: {e}")
        return None

# Load model
model = load_model('model/emotion_model.h5')

# Emotion labels
emotion_labels = ['Angry', 'Disgust', 'Fear', 'Happy', 'Sad', 'Surprise', 'Neutral']

# Load face detector
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')



# Authentication Routes
@app.route('/signup', methods=['POST'])
def signup():
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        username = data.get('username', email.split('@')[0])
        
        print(f"Signup attempt for: {email}")
        
        # Sign up with Supabase
        response = supabase.auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "data": {
                    "username": username
                }
            }
        })
        
        print(f"Signup response: {response}")
        
        if response.user:
            print(f"User created: {response.user.id}")
            
            # Try to sign in immediately after signup (since email confirmation is disabled)
            try:
                login_response = supabase.auth.sign_in_with_password({
                    "email": email,
                    "password": password
                })
                
                if login_response.user and login_response.session:
                    return jsonify({
                        'message': 'User created and logged in successfully',
                        'user': {
                            'id': login_response.user.id,
                            'email': login_response.user.email,
                            'username': username
                        },
                        'session': login_response.session.access_token
                    })
            except Exception as login_error:
                print(f"Auto-login after signup failed: {login_error}")
            
            # Fallback: return signup success without session
            return jsonify({
                'message': 'User created successfully. Please login.',
                'user': {
                    'id': response.user.id,
                    'email': response.user.email,
                    'username': username
                }
            })
        else:
            return jsonify({'error': 'Failed to create user'}), 400
            
    except Exception as e:
        print(f"Signup error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        
        print(f"Login attempt for email: {email}")
        
        # Login with Supabase
        response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        
        print(f"Supabase response: {response}")
        
        if response.user and response.session:
            print(f"Login successful for user: {response.user.id}")
            # Get user profile
            try:
                profile = supabase.table('user_profiles').select('*').eq('user_id', response.user.id).execute()
                username = profile.data[0]['username'] if profile.data else email.split('@')[0]
            except Exception as profile_error:
                print(f"Profile fetch error: {profile_error}")
                # Fallback if profile doesn't exist
                username = email.split('@')[0]
            
            return jsonify({
                'message': 'Login successful',
                'user': {
                    'id': response.user.id,
                    'email': response.user.email,
                    'username': username
                },
                'session': response.session.access_token
            })
        else:
            print("No user or session in response")
            return jsonify({'error': 'Invalid credentials'}), 401
            
    except Exception as e:
        print(f"Login error details: {e}")
        print(f"Error type: {type(e)}")
        return jsonify({'error': f'Login failed: {str(e)}'}), 401

@app.route('/logout', methods=['POST'])
def logout():
    try:
        auth_header = request.headers.get('Authorization')
        if auth_header:
            token = auth_header.replace('Bearer ', '')
            supabase.auth.sign_out()
        return jsonify({'message': 'Logged out successfully'})
    except Exception as e:
        return jsonify({'message': 'Logged out successfully'})

@app.route('/check-auth', methods=['GET'])
def check_auth():
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({'authenticated': False}), 401
            
        token = auth_header.replace('Bearer ', '')
        user = verify_token(token)
        
        if user:
            # Get user profile
            try:
                profile = supabase.table('user_profiles').select('*').eq('user_id', user.id).execute()
                username = profile.data[0]['username'] if profile.data else user.email.split('@')[0]
            except:
                # Fallback if profile doesn't exist
                username = user.email.split('@')[0]
            
            return jsonify({
                'authenticated': True,
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'username': username
                }
            })
        else:
            return jsonify({'authenticated': False}), 401
            
    except Exception as e:
        print(f"Auth check error: {e}")
        return jsonify({'authenticated': False}), 401

@app.route('/predict', methods=['POST'])
def predict():
    try:
        data = request.json
        img_data = data['image']
        print("Received image data")

        # Convert base64 to OpenCV image
        img_bytes = base64.b64decode(img_data.split(',')[1])
        img = Image.open(io.BytesIO(img_bytes)).convert('RGB')
        img = np.array(img)
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

        # Better face detection parameters
        faces = face_cascade.detectMultiScale(
            gray, 
            scaleFactor=1.1, 
            minNeighbors=5, 
            minSize=(30, 30),
            flags=cv2.CASCADE_SCALE_IMAGE
        )
        print(f"Detected {len(faces)} faces")
        results = []

        for (x, y, w, h) in faces:
            # Extract face region
            roi_gray = gray[y:y+h, x:x+w]
            
            # Resize to model input size (64x64)
            roi_gray = cv2.resize(roi_gray, (64, 64))
            
            # Normalize pixel values and ensure correct shape
            roi = roi_gray.astype("float") / 255.0
            roi = np.expand_dims(roi, axis=-1)  # Add channel dimension (64, 64, 1)
            roi = np.expand_dims(roi, axis=0)   # Add batch dimension (1, 64, 64, 1)
            
            print(f"Input shape: {roi.shape}")  # Debug print

            # Predict emotion
            preds = model.predict(roi, verbose=0)[0]
            emotion_idx = np.argmax(preds)
            label = emotion_labels[emotion_idx]
            confidence = float(preds[emotion_idx])
            
            print(f"Detected emotion: {label} with confidence: {confidence:.2f}")

            results.append({
                'label': label,
                'confidence': confidence,
                'box': {'x': int(x), 'y': int(y), 'w': int(w), 'h': int(h)}
            })

        return jsonify(results)
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
