"""API v1 package — registers sub-blueprints."""
from flask import Blueprint

v1_bp = Blueprint("v1", __name__, url_prefix="/api/v1")
_SUB_BLUEPRINTS_REGISTERED = False


def register_v1_blueprints(app):
    """Register all v1 route blueprints onto the v1 parent blueprint."""
    global _SUB_BLUEPRINTS_REGISTERED
    if not _SUB_BLUEPRINTS_REGISTERED:
        from app.api.v1.alerts import alerts_bp
        from app.api.v1.auth import auth_bp
        from app.api.v1.capture import capture_bp
        from app.api.v1.health import health_bp
        from app.api.v1.monitoring import monitoring_bp
        from app.api.v1.predict import predict_bp

        v1_bp.register_blueprint(auth_bp)
        v1_bp.register_blueprint(health_bp)
        v1_bp.register_blueprint(predict_bp)
        v1_bp.register_blueprint(alerts_bp)
        v1_bp.register_blueprint(monitoring_bp)
        v1_bp.register_blueprint(capture_bp, url_prefix="/capture")
        _SUB_BLUEPRINTS_REGISTERED = True

    app.register_blueprint(v1_bp)
