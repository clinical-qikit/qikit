# QiKit Excel Add-in Deployment Guide

This guide provides instructions on how to deploy and distribute the QiKit Excel Add-in.

## 1. Build the Add-in

Before deployment, you need to build the optimized static assets:

```bash
cd excel-addin
npm install
npm run build
```

This command will output the production-ready static files into the `excel-addin/dist` directory. The build is optimized with Vite (tree shaking and code splitting).

## 2. Host the Task Pane Application (HTTPS Required)

Office Add-ins **must** be hosted on a secure HTTPS server.

You can choose one of the following hosting options:

### Option A: GitHub Pages (Recommended for Open Source)
1. Commit the contents of your `dist` folder to a `gh-pages` branch or configure GitHub Actions to deploy the `dist` folder.
2. Ensure you configure GitHub Pages in your repository settings to enforce HTTPS.
3. Update the `manifest.json` source locations with your GitHub Pages URL (e.g., `https://username.github.io/qikit/taskpane.html`).

### Option B: Azure Static Web Apps (Free Tier)
1. Go to the Azure Portal and create a new Static Web App.
2. Connect your GitHub repository.
3. Set the build preset to "Vite" or use the custom build details:
   - App location: `/excel-addin`
   - Output location: `dist`
4. Once deployed, Azure provides a free automatic HTTPS certificate. Update your `manifest.json` with the assigned URL.

### Option C: Hospital / University Intranet (Internal Deployment)
1. Deploy the `dist` folder to your internal web server (e.g., IIS, Nginx, or Apache).
2. **Important:** Ensure the server is configured with a valid SSL/TLS certificate. Self-signed certificates may require trusting them on client machines.
3. Update `manifest.json` URLs accordingly.

## 3. Update the Manifest File

Before distributing the add-in, update the `<SourceLocation>` and any icon URLs in `manifest.json` to point to your new HTTPS-hosted URL.

* Example change in `manifest.json`:
  ```json
  "SourceLocation": "https://your-hosting-url.com/taskpane.html"
  ```

## 4. Distribution Methods

Once the web application is hosted and the manifest is updated, you can distribute the add-in using one of these methods:

### Method 1: Centralized Deployment (For IT Admins / Organizations)
Recommended for hospitals and universities.
1. Go to the Microsoft 365 Admin Center.
2. Navigate to **Settings > Integrated apps** (or **Settings > Services & add-ins**).
3. Click **Upload custom apps**.
4. Upload your updated `manifest.json` file.
5. Assign access to specific users, groups, or the entire organization.

### Method 2: Network Share / Sideloading (For Small Teams or Testing)
1. Place the `manifest.json` file on a shared network drive accessible by the users.
2. Users open Excel > **Options > Trust Center > Trust Center Settings > Trusted Add-in Catalogs**.
3. Add the network path as a Trusted Catalog and check "Show in Menu".
4. Users can now install it via **Insert > Get Add-ins > Shared Folder**.

## 5. Troubleshooting
- **Blank Task Pane:** Ensure your hosting uses HTTPS and no mixed-content (HTTP) errors are occurring.
- **Manifest Errors:** Use the command `npm run validate` (if available via office-addin-manifest) to validate your manifest file before distribution.
