"""GCS client abstraction with Application Default Credentials (ADC) authentication."""

from google.auth.exceptions import DefaultCredentialsError
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
            "     credentials_path = '/path/to/service-account.json'\n"
        ) from e

    except Exception as e:
        raise RuntimeError(f"Failed to create GCS storage client: {e}") from e


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

    except Exception as e:
        if "does not exist" in str(e).lower():
            raise RuntimeError(
                f"GCS bucket '{bucket_name}' does not exist.\n\n"
                f"Create the bucket:\n"
                f"  gcloud storage buckets create gs://{bucket_name} --location=us-central1"
            ) from e

        if "permission" in str(e).lower() or "forbidden" in str(e).lower():
            raise RuntimeError(
                f"Insufficient permissions for GCS bucket '{bucket_name}'.\n\n"
                f"Grant required permissions:\n"
                f"  - storage.buckets.get\n"
                f"  - storage.objects.create\n"
                f"  - storage.objects.delete\n"
                f"  - storage.objects.get\n"
                f"  - storage.objects.list\n\n"
                f"Or use a service account with Storage Admin role:\n"
                f"  gcloud projects add-iam-policy-binding PROJECT_ID \\\n"
                f"    --member='serviceAccount:SERVICE_ACCOUNT@PROJECT_ID.iam.gserviceaccount.com' \\\n"
                f"    --role='roles/storage.admin'"
            ) from e

        raise RuntimeError(f"Failed to validate bucket access: {e}") from e
