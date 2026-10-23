"""API v1 package — registers sub-blueprints."""
from flask import Blueprint

v1_bp = Blueprint("v1", __name__, url_prefix="/api/v1")


def register_v1_blueprints(app):
    """Register all v1 route blueprints onto the v1 parent blueprint."""
    from app.api.v1.health import health_bp
    from app.api.v1.predict import predict_bp

    v1_bp.register_blueprint(health_bp)
    v1_bp.register_blueprint(predict_bp)
    app.register_blueprint(v1_bp)
