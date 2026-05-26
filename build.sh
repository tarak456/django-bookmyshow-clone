#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate

# Auto-create superuser if it doesn't exist (free alternative to shell)
python manage.py shell << 'PYEOF'
from django.contrib.auth.models import User
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@bookmyseat.com', 'Admin@1234')
    print('Superuser created: admin / Admin@1234')
else:
    print('Superuser already exists')
PYEOF
