import os
import warnings
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv

# Suprime aviso de depreciação do pkg_resources (usado por docxcompose)
warnings.filterwarnings(
    "ignore",
    message="pkg_resources is deprecated",
    category=UserWarning,
)
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Básico / Prod-friendly defaults ---
SECRET_KEY = os.getenv("SECRET_KEY", "dev-unsafe-change-me")
DEBUG = os.getenv("DEBUG", "0") == "1"  # default OFF; ligue com DEBUG=1 no .env
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    # Apps do projeto
    "accounts",
    "templates_app",
    "petitions",
    "cadastro",
    "reports",
    "contracts",
    "kits",
    "advogados",
    "permissoes",
]

MIDDLEWARE = [
    # CORS deve vir o mais alto possível
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "jurisdoc.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "jurisdoc.wsgi.application"

# --- Banco ---
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "jurisdoc"),
        "USER": os.getenv("DB_USER", "jurisdoc_user"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }
}

# --- Senhas ---
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Localização & TZ ---
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

# --- Static/Media ---
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # útil se você decidir servir estáticos em prod
MEDIA_URL = "/media/"
MEDIA_ROOT = os.getenv("MEDIA_ROOT", str(BASE_DIR / "media"))

# WhiteNoise: compressão e hash de arquivo para cache busting
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Se houver uma pasta raiz "static/", descomente abaixo
# STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- DRF ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "jurisdoc.pagination.DefaultPagination",
    "PAGE_SIZE": 20,
    # Não liga throttling global — só fornece a taxa para os throttles que a
    # declaram. "app_login": tentativas de login do app FlowALR, por username.
    "DEFAULT_THROTTLE_RATES": {
        "app_login": "10/min",
        # Área "Sou cliente" do app — chaveados por CPF/e-mail, não por IP
        "cliente_app_login": "10/min",
        "cliente_app_senha": "5/min",
        # Código por WhatsApp: o envio é o recurso escasso (o WhatsApp limita
        # conversas novas), então o teto é por hora e por telefone.
        "cliente_app_codigo_envio": "5/hour",
        "cliente_app_codigo_validacao": "15/hour",
    },
}

# --- JWT ---
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),  # ajuste se quiser mais/menos
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

# --- OpenAPI ---
SPECTACULAR_SETTINGS = {
    "TITLE": "JurisDoc API",
    "VERSION": "0.1.0",
}

CSRF_TRUSTED_ORIGINS = os.getenv(
    "CSRF_TRUSTED_ORIGINS",
    ",".join(
        [
            "http://127.0.0.1:4173",
            "http://localhost:4173",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://localhost:3000",
            "http://192.168.0.250:8000",
            "http://192.168.0.250",
            "http://127.0.0.1",
            "http://localhost",
            "http://jurisdoc.local",
            "https://jurisdoc-frontend.hqdg0k.easypanel.host",
            "https://jurisdoc-backend.hqdg0k.easypanel.host",
            "https://api.azevedoerebonatto.com.br",
            "https://jurisdoc.azevedoerebonatto.com.br",
        ]
    ),
).split(",")

# Abrir CORS para todas as origens (atenção: não use com credenciais)
# Proxy reverso (EasyPanel/Nginx) envia HTTPS como X-Forwarded-Proto
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

CORS_ALLOW_ALL_ORIGINS = True

# Usuário customizado
AUTH_USER_MODEL = "accounts.User"

# Chave de assinatura para tokens de serviço (Client Credentials).
# Em produção defina APP_INTEGRATION_SECRET no .env com um valor aleatório longo.
APP_INTEGRATION_SECRET = os.getenv("APP_INTEGRATION_SECRET", SECRET_KEY)

# Token da API ZapSign (assinatura eletrônica). Defina ZAPSIGN_API_TOKEN no .env / EasyPanel.
ZAPSIGN_API_TOKEN = os.getenv("ZAPSIGN_API_TOKEN", "")

# Origem pública deste backend (sem barra final). Usada para montar o link do
# portal de assinatura entregue ao cliente e o redirect_link enviado ao ZapSign.
# Quando vazio, o link é derivado do request que originou o envio.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")

# Máquinas com inspeção de TLS (antivírus/proxy corporativo) fazem o Python
# recusar certificados válidos — a CA da interceptação está no repositório do
# Windows, não no bundle do certifi. `truststore` passa a usar o repositório do
# SO (não desliga a validação). Opt-in, para não alterar o comportamento em
# produção: defina USE_SYSTEM_CERTS=1 e instale `truststore` no ambiente local.
if os.getenv("USE_SYSTEM_CERTS", "0") == "1":
    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:
        pass

# --- uazapi (código de acesso do cliente por WhatsApp) ---
# Usado só pela área "Sou cliente" do app FlowALR. Sem estas variáveis o login
# por WhatsApp responde 503 e o acesso alternativo (e-mail/senha) segue valendo.
UAZAPI_BASE_URL = os.getenv("UAZAPI_BASE_URL", "")
UAZAPI_INSTANCE_TOKEN = os.getenv("UAZAPI_INSTANCE_TOKEN", "")
# Nome que aparece no início da mensagem enviada ao cliente.
APP_CLIENTE_NOME = os.getenv("APP_CLIENTE_NOME", "FlowALR")

# --- OpenAI (leitura de documentos do cliente por IA) ---
# Sem OPENAI_API_KEY o endpoint responde 503 e o preenchimento manual segue normal.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
# Comprovantes de residência: texto corrido, o mini resolve bem e é ~10x mais barato.
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
# RG/CNH: layout denso e texto miúdo — o mini erra sistematicamente aqui.
OPENAI_MODEL_IDENTIDADE = os.getenv("OPENAI_MODEL_IDENTIDADE", "gpt-4o")

# Google Places API (autocomplete de endereço via proxy do backend).
# A mesma chave do front pode ser usada aqui. Como ela é restrita por HTTP
# referrer, o backend envia GOOGLE_MAPS_PLACES_REFERER (um referrer permitido
# pela chave, ex.: http://localhost:3000) para a chamada REST ser aceita em produção.
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
GOOGLE_MAPS_PLACES_REFERER = os.getenv("GOOGLE_MAPS_PLACES_REFERER", "http://localhost:3000")

# Log de erros 500 no console (Gunicorn/EasyPanel) para ver traceback com DEBUG=0
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        # Logs das integrações aparecem no EasyPanel (INFO e acima)
        "kits": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "accounts": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
