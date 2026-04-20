# Implementation Plan: Hosting CLM SOA Application

The goal is to move the local application to a hosted environment (Render) so it's accessible via a public URL.

## 1. Prepare Code for Production
- [ ] **Update `app.py`**: Modify the `app.run()` to use `0.0.0.0` and bind to the `$PORT` environment variable.
- [ ] **Synchronize Dockerfile**: Ensure the `Dockerfile` matches the application port and configuration.
- [ ] **Add `gunicorn`**: Add a production-grade WSGI server to `requirements.txt`.

## 2. Infrastructure as Code
- [ ] **Create `render.yaml`**: Define the service configuration for Render, including the web service and environment variables.

## 3. Configuration
- [ ] Map the Redshift credentials from `.env` to Render Environment Variables.

## 4. Deployment Instructions
- [ ] Connect the GitHub repository to Render.
- [ ] Deploy the service.

---

### Step 1: Update `app.py`
Modify the entry point:
```python
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
```

### Step 2: Update `requirements.txt`
Add `gunicorn`.

### Step 3: Create `render.yaml`
```yaml
services:
  - type: web
    name: clm-soa
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn app:app
    envVars:
      - key: REDSHIFT_HOST
        sync: false
      - key: REDSHIFT_PORT
        sync: false
      - key: REDSHIFT_DB
        sync: false
      - key: REDSHIFT_USER
        sync: false
      - key: REDSHIFT_PASSWORD
        sync: false
```
