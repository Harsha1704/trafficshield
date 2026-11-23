"""API v1 package — registers sub-blueprints."""
from flask import Blueprint

v1_bp = Blueprint("v1", __name__, url_prefix="/api/v1")
_SUB_BLUEPRINTS_REGISTERED = False


@v1_bp.route("", methods=["GET"])
@v1_bp.route("/", methods=["GET"])
def v1_root():
    """Service status and endpoint index for API v1 root."""
    return {
        "success": True,
        "data": {
            "service": "TrafficShield API",
            "version": "1.0.0",
            "status": "online",
            "api_version": "v1",
            "docs": "/api/v1/health",
            "endpoints": {
                "health": "/api/v1/health",
                "ready": "/api/v1/ready",
                "auth": "/api/v1/auth",
                "predict": "/api/v1/predict",
                "alerts": "/api/v1/alerts",
                "monitoring": "/api/v1/monitoring",
                "capture": "/api/v1/capture",
            },
        },
    }, 200


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
