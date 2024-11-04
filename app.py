from flask import Flask, request, jsonify, render_template 
from flask_cors import CORS
from flask_pymongo import PyMongo
import instaloader
from datetime import datetime, timedelta
import pandas as pd
import os
from dotenv import load_dotenv
import logging
import sys
import traceback
from bson import ObjectId

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('debug.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
logger.debug("Loading environment variables...")
try:
    load_dotenv()
    logger.debug("Environment variables loaded successfully")
except Exception as e:
    logger.error(f"Failed to load environment variables: {str(e)}")
    raise

app = Flask(__name__)
logger.debug("Flask app initialized")

# Enable CORS
try:
    CORS(app)
    logger.debug("CORS enabled successfully")
except Exception as e:
    logger.error(f"Failed to enable CORS: {str(e)}")
    raise

# MongoDB configuration
logger.debug("Configuring MongoDB connection...")
try:
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/influencer_analytics")
    app.config["MONGO_URI"] = mongo_uri
    mongo = PyMongo(app)
    mongo.db.command('ping')
    logger.debug("MongoDB connected successfully")
except Exception as e:
    logger.error(f"MongoDB connection failed: {str(e)}")
    raise

# Initialize Instaloader
logger.debug("Initializing Instaloader...")
try:
    L = instaloader.Instaloader()
    L.load_session_from_file('mart.e827')
    logger.debug("Instaloader initialized successfully with session")
except Exception as e:
    logger.error(f"Failed to initialize Instaloader with session: {str(e)}")
    raise

def get_profile_metrics(username):
    """Fetch profile metrics using Instaloader"""
    logger.debug(f"Fetching metrics for username: {username}")
    
    try:
        profile = instaloader.Profile.from_username(L.context, username)
        logger.debug(f"Profile loaded successfully for {username}")
        
        posts_data = []
        post_count = 0
        total_likes = 0
        total_comments = 0
        
        logger.debug("Starting to fetch recent posts...")
        current_time = datetime.now()
        cutoff_date = current_time - timedelta(days=30)
        
        for post in profile.get_posts():
            if post.date > cutoff_date:
                post_count += 1
                total_likes += post.likes
                total_comments += post.comments
                posts_data.append({
                    'timestamp': post.date.isoformat(),
                    'likes': post.likes,
                    'comments': post.comments
                })
                logger.debug(f"Processed post {post_count}: Likes={post.likes}, Comments={post.comments}")
            if post_count >= 30:
                break
                
        logger.debug(f"Completed posts collection. Total posts processed: {post_count}")
        
        engagement_rate = ((total_likes + total_comments) / profile.followers / post_count * 100) if post_count > 0 and profile.followers > 0 else 0
        
        metrics = {
            'username': username,
            'follower_count': profile.followers,
            'following_count': profile.followees,
            'post_count': profile.mediacount,
            'avg_likes': total_likes / post_count if post_count > 0 else 0,
            'avg_comments': total_comments / post_count if post_count > 0 else 0,
            'engagement_rate': engagement_rate,
            'posts_data': posts_data
        }
        
        logger.debug(f"Metrics calculated successfully: {metrics}")
        return metrics
        
    except Exception as e:
        error_msg = f"Error fetching profile metrics: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return {'error': error_msg}

def calculate_revenue_estimate(metrics, conversion_rate, avg_order_value):
    """Calculate estimated revenue based on reach and conversion rate"""
    logger.debug(f"Calculating revenue with conversion_rate={conversion_rate}%, avg_order_value=${avg_order_value}")
    
    try:
        follower_count = metrics['follower_count']
        
        # Calculate minimum and maximum reach
        min_reach = follower_count / 0.4  # Followers are 40% of total reach
        max_reach = follower_count / 0.2  # Followers are 20% of total reach
        
        # Calculate estimated sales
        conversion_rate_decimal = conversion_rate / 100
        min_sales = min_reach * conversion_rate_decimal
        max_sales = max_reach * conversion_rate_decimal
        
        # Calculate estimated revenue
        min_revenue = min_sales * avg_order_value
        max_revenue = max_sales * avg_order_value
        
        result = {
            'follower_count': follower_count,
            'min_reach': min_reach,
            'max_reach': max_reach,
            'min_sales': min_sales,
            'max_sales': max_sales,
            'min_revenue': min_revenue,
            'max_revenue': max_revenue,
            'conversion_rate': conversion_rate,
            'avg_order_value': avg_order_value
        }
        
        logger.debug(f"Revenue calculation completed: {result}")
        return result
        
    except Exception as e:
        error_msg = f"Error calculating revenue estimate: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return {'error': error_msg}

@app.route('/')
def home():
    logger.debug("Serving home page")
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze_profile():
    logger.debug("Received analyze profile request")
    
    try:
        data = request.json
        logger.debug(f"Request data: {data}")
        
        username = data.get('username')
        if not username:
            error_msg = "Username is required"
            logger.error(error_msg)
            return jsonify({'error': error_msg}), 400
            
        conversion_rate = float(data.get('conversion_rate', 1.0))
        avg_order_value = float(data.get('avg_order_value', 50.0))
        
        # Get metrics
        metrics = get_profile_metrics(username)
        if 'error' in metrics:
            return jsonify(metrics), 400
            
        # Calculate revenue estimates
        revenue_analysis = calculate_revenue_estimate(metrics, conversion_rate, avg_order_value)
        if 'error' in revenue_analysis:
            return jsonify(revenue_analysis), 400
        
        result = {
            'profile_metrics': metrics,
            'revenue_analysis': revenue_analysis,
            'timestamp': datetime.now().isoformat()
        }
        
        # Store in MongoDB
        try:
            mongo_result = mongo.db.analyses.insert_one(result)
            result['_id'] = str(mongo_result.inserted_id)
            logger.debug("Results stored successfully")
        except Exception as e:
            logger.error(f"Failed to store results in MongoDB: {str(e)}")
        
        logger.debug("Analysis completed successfully")
        return jsonify(result)
        
    except Exception as e:
        error_msg = f"Unexpected error in analyze_profile: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return jsonify({'error': error_msg}), 500

@app.route('/compare', methods=['POST'])
def compare_profiles():
    logger.debug("Received compare profiles request")
    
    try:
        data = request.json
        usernames = data.get('usernames', [])
        conversion_rate = float(data.get('conversion_rate', 1.0))
        avg_order_value = float(data.get('avg_order_value', 50.0))
        
        if not usernames or len(usernames) < 2:
            error_msg = "At least two usernames are required"
            logger.error(error_msg)
            return jsonify({'error': error_msg}), 400
            
        results = []
        for username in usernames:
            logger.debug(f"Analyzing profile: {username}")
            metrics = get_profile_metrics(username)
            if 'error' not in metrics:
                revenue_analysis = calculate_revenue_estimate(metrics, conversion_rate, avg_order_value)
                results.append({
                    'username': username,
                    'metrics': metrics,
                    'revenue_analysis': revenue_analysis
                })
            else:
                logger.error(f"Error analyzing {username}: {metrics['error']}")
        
        # Sort results by maximum revenue potential
        sorted_results = sorted(results, 
                              key=lambda x: x['revenue_analysis']['max_revenue'], 
                              reverse=True)
        
        comparison = {
            'profiles': sorted_results,
            'timestamp': datetime.now().isoformat()
        }
        
        logger.debug("Comparison completed successfully")
        return jsonify(comparison)
        
    except Exception as e:
        error_msg = f"Unexpected error in compare_profiles: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return jsonify({'error': error_msg}), 500

if __name__ == '__main__':
    logger.info("Starting Flask application...")
    app.run(debug=True)