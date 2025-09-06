# JurisDoc (Skeleton)

Backend Django + DRF + JWT para geração de petições (.docx) com `docxtpl`.

## Passos rápidos

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
python manage.py migrate
python manage.py createsuperuser  # admin inicial
python manage.py runserver 0.0.0.0:8000
```

Rotas úteis:
- `/api/auth/login/` (JWT)
- `/api/templates/` (CRUD de modelos .docx - admin)
- `/api/petitions/generate/` (gerar petição)
- `/api/docs/` (Swagger UI)
