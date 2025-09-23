// ecosystem.config.js
module.exports = {
  apps: [
    {
      name: 'jurisdoc',
      cwd: 'C:/jurisdoc-backend/jurisdoc-backend',
      script:
        'C:/Users/tiago/AppData/Local/Programs/Python/Python313/Scripts/waitress-serve.exe',
      // use host/port para evitar ambiguidade com '='
      args: '--host=0.0.0.0 --port=8000 jurisdoc.wsgi:application',
      autorestart: true,
      watch: false,
      out_file: 'C:/logs/jurisdoc.out.log',
      error_file: 'C:/logs/jurisdoc.err.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
    },
  ],
};
