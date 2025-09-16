from django.db import migrations

SQL = """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    WHERE t.relname = 'cadastro_descricaobanco'
      AND c.contype = 'u'
      AND c.conname = 'cadastro_descricaobanco_banco_id_key'
  ) THEN
    ALTER TABLE cadastro_descricaobanco
      DROP CONSTRAINT cadastro_descricaobanco_banco_id_key;
  END IF;
END$$;
"""

class Migration(migrations.Migration):
    dependencies = [
        ('cadastro', '0004_alter_descricaobanco_options_descricaobanco_is_ativa_and_more'),  # <-- TROQUE AQUI
    ]
    operations = [
        migrations.RunSQL(SQL, reverse_sql=""),
    ]
