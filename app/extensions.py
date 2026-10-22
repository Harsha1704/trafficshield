"""
Flask Extensions
=================
Initializes all Flask extension singletons here, so they can be imported
without triggering circular imports. Each extension is bound to the app
in the application factory (app/__init__.py).
"""
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
migrate = Migrate()
cors = CORS()
limiter = Limiter(key_func=get_remote_address)
