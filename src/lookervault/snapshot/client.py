"""GCS client abstraction with Application Default Credentials (ADC) authentication."""

from google.auth.exceptions import DefaultCredentialsError, RefreshError
from google.cloud import exceptions as gcs_exceptions
from google.cloud import storage


def create_storage_client(project_id: str | None = None) -> storage.Client:
    """
    Create a GCS storage client using Application Default Credentials.

    Args:
        project_id: Optional GCP project ID. Auto-detected from credentials if None.

    Returns:
        Authenticated storage.Client instance

    Raises:
        RuntimeError: If no valid credentials are found

    Authentication Sources (in order of precedence):
        1. GOOGLE_APPLICATION_CREDENTIALS environment variable
        2. gcloud auth application-default credentials
        3. GCE/GKE service account (when running on GCP)
    """
    try:
        if project_id:
            client = storage.Client(project=project_id)
        else:
            # Auto-detect project from credentials
            client = storage.Client()

        # Verify authentication by testing bucket list (doesn't actually list)
        # This will raise if credentials are invalid
        _ = client.project

        return client

    except DefaultCredentialsError as e:
        raise RuntimeError(
            "No valid Google Cloud credentials found.\n\n"
            "Solutions:\n"
            "  1. Set GOOGLE_APPLICATION_CREDENTIALS environment variable:\n"
            "     export GOOGLE_APPLICATION_CREDENTIALS='/path/to/service-account.json'\n\n"
            "  2. Run gcloud auth application-default login:\n"
            "     gcloud auth application-default login\n\n"
            "  3. Configure service account in lookervault.toml:\n"
            "     [snapshot]\n"
            "     credentials_path = '/path/to/service-account.json'\n\n"
            "Troubleshooting:\n"
            "  - Verify credentials file exists and has valid JSON format\n"
            "  - Check file permissions (should be readable)\n"
            "  - Ensure gcloud CLI is installed: gcloud version\n"
            "  - Verify active gcloud account: gcloud auth list\n"
            "  - If using service account, verify it's enabled in GCP Console\n"
        ) from e

    except RefreshError as e:
        raise RuntimeError(
            "Failed to refresh Google Cloud credentials.\n\n"
            "This usually means your credentials have expired or are invalid.\n\n"
            "Solutions:\n"
            "  1. Re-authenticate with gcloud:\n"
            "     gcloud auth application-default login\n\n"
            "  2. If using service account, generate a new key:\n"
            "     gcloud iam service-accounts keys create key.json \\\n"
            "       --iam-account=SERVICE_ACCOUNT@PROJECT.iam.gserviceaccount.com\n\n"
            "  3. Verify service account is not disabled:\n"
            "     gcloud iam service-accounts describe SERVICE_ACCOUNT@PROJECT.iam.gserviceaccount.com\n\n"
            "Troubleshooting:\n"
            "  - Check if credentials file is corrupted or modified\n"
            "  - Verify service account still exists in GCP Console\n"
            "  - Ensure service account key is not expired or revoked\n"
            f"  - Error details: {e}\n"
        ) from e

    except Exception as e:
        error_msg = str(e).lower()

        # Enhanced error message for permission/authorization errors
        if "permission" in error_msg or "forbidden" in error_msg or "unauthorized" in error_msg:
            raise RuntimeError(
                "Authentication failed: Insufficient permissions or unauthorized access.\n\n"
                "Common causes:\n"
                "  - Service account lacks required permissions\n"
                "  - Credentials are valid but not authorized for this project\n"
                "  - API is disabled for the project\n\n"
                "Solutions:\n"
                "  1. Verify service account has required roles:\n"
                "     gcloud projects get-iam-policy PROJECT_ID \\\n"
                "       --flatten='bindings[].members' \\\n"
                "       --filter='bindings.members:serviceAccount:YOUR_SA@PROJECT.iam.gserviceaccount.com'\n\n"
                "  2. Grant Storage Admin role:\n"
                "     gcloud projects add-iam-policy-binding PROJECT_ID \\\n"
                "       --member='serviceAccount:YOUR_SA@PROJECT.iam.gserviceaccount.com' \\\n"
                "       --role='roles/storage.admin'\n\n"
                "  3. Enable Cloud Storage API:\n"
                "     gcloud services enable storage.googleapis.com --project=PROJECT_ID\n\n"
                f"  Error details: {e}\n"
            ) from e

        # Enhanced error message for project-related errors
        if "project" in error_msg or "quota" in error_msg:
            raise RuntimeError(
                "Failed to create GCS storage client: Project configuration error.\n\n"
                "Common causes:\n"
                "  - Invalid or missing project ID\n"
                "  - Project is disabled or deleted\n"
                "  - Billing is not enabled for the project\n"
                "  - API quota exceeded\n\n"
                "Solutions:\n"
                "  1. Verify project exists and is active:\n"
                "     gcloud projects describe PROJECT_ID\n\n"
                "  2. Enable billing for the project:\n"
                "     https://console.cloud.google.com/billing\n\n"
                "  3. Check API quotas:\n"
                "     https://console.cloud.google.com/apis/api/storage.googleapis.com/quotas\n\n"
                "  4. Specify project explicitly in lookervault.toml:\n"
                "     [snapshot]\n"
                "     project_id = 'your-project-id'\n\n"
                f"  Error details: {e}\n"
            ) from e

        # Generic error with basic troubleshooting
        raise RuntimeError(
            f"Failed to create GCS storage client: {e}\n\n"
            "Troubleshooting:\n"
            "  - Verify network connectivity to Google Cloud APIs\n"
            "  - Check gcloud authentication: gcloud auth list\n"
            "  - Ensure Cloud Storage API is enabled\n"
            "  - Review error details above for specific issues\n"
        ) from e


def validate_bucket_access(client: storage.Client, bucket_name: str) -> bool:
    """
    Validate that the client has access to the specified GCS bucket.

    Args:
        client: Authenticated storage.Client instance
        bucket_name: Name of the GCS bucket to validate

    Returns:
        True if bucket exists and client has access

    Raises:
        RuntimeError: If bucket doesn't exist or client lacks permissions
    """
    try:
        bucket = client.bucket(bucket_name)

        # Test access by checking if bucket exists
        if not bucket.exists():
            raise RuntimeError(
                f"GCS bucket '{bucket_name}' does not exist.\n\n"
                f"Create the bucket:\n"
                f"  gcloud storage buckets create gs://{bucket_name} --location=us-central1\n\n"
                f"Or update lookervault.toml with an existing bucket name."
            )

        # Test write permissions by attempting to get bucket metadata
        bucket.reload()

        return True

    except gcs_exceptions.NotFound as e:
        raise RuntimeError(
            f"GCS bucket '{bucket_name}' does not exist.\n\n"
            f"Solutions:\n"
            f"  1. Create the bucket:\n"
            f"     gcloud storage buckets create gs://{bucket_name} --location=us-central1\n\n"
            f"  2. Or use an existing bucket in lookervault.toml:\n"
            f"     [snapshot]\n"
            f"     bucket_name = 'your-existing-bucket'\n\n"
            f"  3. List available buckets:\n"
            f"     gcloud storage buckets list --project=PROJECT_ID\n"
        ) from e

    except (gcs_exceptions.Forbidden, gcs_exceptions.Unauthorized) as e:
        raise RuntimeError(
            f"Insufficient permissions for GCS bucket '{bucket_name}'.\n\n"
            f"Required permissions:\n"
            f"  - storage.buckets.get\n"
            f"  - storage.objects.create\n"
            f"  - storage.objects.delete\n"
            f"  - storage.objects.get\n"
            f"  - storage.objects.list\n\n"
            f"Solutions:\n"
            f"  1. Grant Storage Admin role (recommended):\n"
            f"     gcloud storage buckets add-iam-policy-binding gs://{bucket_name} \\\n"
            f"       --member='serviceAccount:YOUR_SA@PROJECT.iam.gserviceaccount.com' \\\n"
            f"       --role='roles/storage.admin'\n\n"
            f"  2. Or grant minimal permissions:\n"
            f"     gcloud storage buckets add-iam-policy-binding gs://{bucket_name} \\\n"
            f"       --member='serviceAccount:YOUR_SA@PROJECT.iam.gserviceaccount.com' \\\n"
            f"       --role='roles/storage.objectAdmin'\n\n"
            f"  3. Verify current permissions:\n"
            f"     gcloud storage buckets get-iam-policy gs://{bucket_name}\n\n"
            f"Troubleshooting:\n"
            f"  - Ensure you're using the correct service account\n"
            f"  - Check if bucket has organization policies restricting access\n"
            f"  - Verify Cloud Storage API is enabled for the project\n"
        ) from e

    except Exception as e:
        error_msg = str(e).lower()

        # Enhanced error message for network/connectivity errors
        if (
            "connection" in error_msg
            or "timeout" in error_msg
            or "network" in error_msg
            or "dns" in error_msg
            or "unreachable" in error_msg
        ):
            raise RuntimeError(
                f"Network error while accessing GCS bucket '{bucket_name}'.\n\n"
                f"Common causes:\n"
                f"  - Network connectivity issues\n"
                f"  - Firewall blocking Google Cloud APIs\n"
                f"  - DNS resolution problems\n"
                f"  - VPN or proxy configuration issues\n\n"
                f"Solutions:\n"
                f"  1. Test connectivity to Google Cloud:\n"
                f"     curl -I https://storage.googleapis.com\n\n"
                f"  2. Check DNS resolution:\n"
                f"     nslookup storage.googleapis.com\n\n"
                f"  3. Verify firewall allows HTTPS (port 443) to Google Cloud APIs\n\n"
                f"  4. If using VPN/proxy, ensure it allows Google Cloud traffic\n\n"
                f"  5. Try again - network issues are often transient\n\n"
                f"  Error details: {e}\n"
            ) from e

        # Generic bucket validation error
        raise RuntimeError(
            f"Failed to validate bucket access for '{bucket_name}'.\n\n"
            f"Troubleshooting:\n"
            f"  1. Verify bucket name is correct:\n"
            f"     gcloud storage buckets describe gs://{bucket_name}\n\n"
            f"  2. Check your credentials and permissions:\n"
            f"     gcloud auth list\n"
            f"     gcloud storage buckets get-iam-policy gs://{bucket_name}\n\n"
            f"  3. Ensure Cloud Storage API is enabled:\n"
            f"     gcloud services enable storage.googleapis.com\n\n"
            f"  Error details: {e}\n"
        ) from e
