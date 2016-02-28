import db
import db.exceptions
import db.dataset
import db.data
from utils import dataset_validator

# Job statuses are defined in `eval_job_status` type. See schema definition.
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


def evaluate_dataset(dataset_id):
    """Add dataset into evaluation queue.

    Args:
        dataset_id: ID of the dataset that needs to be added into the list of
            jobs.

    Returns:
        ID of the newly created evaluation job.
    """
    with db.engine.begin() as connection:
        result = connection.execute(
            "SELECT count(*) FROM dataset_eval_jobs WHERE dataset_id = %s AND status IN %s",
            (dataset_id, (STATUS_PENDING, STATUS_RUNNING))
        )
        if result.fetchone()[0] > 0:
            raise JobExistsException
        validate_dataset(db.dataset.get(dataset_id))
        return _create_job(connection, dataset_id)


def validate_dataset(dataset):
    """Validate dataset by making sure that it matches JSON Schema for complete
    datasets (JSON_SCHEMA_COMPLETE) and checking if all recordings referenced
    in classes have low-level information in the database.

    Raises IncompleteDatasetException if dataset is not ready for evaluation.
    """
    dataset_validator.validate(dataset, complete=True)

    rec_memo = {}
    for cls in dataset["classes"]:
        for recording_mbid in cls["recordings"]:
            if recording_mbid in rec_memo and rec_memo[recording_mbid]:
                pass
            if db.data.count_lowlevel(recording_mbid) > 0:
                rec_memo[recording_mbid] = True
            else:
                # TODO: Create a proper class for this exception:
                raise Exception(
                    "Can't find low-level data for recording: %s" % recording_mbid)


def get_next_pending_job():
    with db.engine.connect() as connection:
        result = connection.execute(
            "SELECT id, dataset_id, status, status_msg, result, created, updated "
            "FROM dataset_eval_jobs "
            "WHERE status = %s "
            "ORDER BY created ASC "
            "LIMIT 1",
            (STATUS_PENDING,)
        )
        row = result.fetchone()
        return dict(row) if row else None


def get_job(job_id):
    with db.engine.connect() as connection:
        result = connection.execute(
            "SELECT id, dataset_id, status, status_msg, result, created, updated "
            "FROM dataset_eval_jobs "
            "WHERE id = %s",
            (job_id,)
        )
        row = result.fetchone()
        return dict(row) if row else None


def get_jobs_for_dataset(dataset_id):
    """Get a list of evaluation jobs for the specified dataset.

    Args:
        dataset_id: UUID of the dataset.

    Returns:
        List of evaluation jobs (dicts) for the dataset. Ordered by creation
        time (oldest job first)
    """
    with db.engine.connect() as connection:
        result = connection.execute(
            "SELECT id, dataset_id, status, status_msg, result, created, updated "
            "FROM dataset_eval_jobs "
            "WHERE dataset_id = %s "
            "ORDER BY created ASC",
            (dataset_id,)
        )
        return [dict(j) for j in result.fetchall()]


def set_job_result(job_id, result):
    with db.engine.begin() as connection:
        result = connection.execute(
            "UPDATE dataset_eval_jobs "
            "SET (result, updated) = (%s, current_timestamp) "
            "WHERE id = %s",
            (result, job_id)
        )


def set_job_status(job_id, status, status_msg=None):
    """Set status for existing job.

    Args:
        job_id: ID of the job that needs a status update.
        status: One of statuses: STATUS_PENDING, STATUS_RUNNING, STATUS_DONE,
            or STATUS_FAILED.
        status_msg: Optional status message that can be used to provide
            additional information about status that is being set. For example,
            error message if it's STATUS_FAILED.
    """
    if status not in [STATUS_PENDING,
                      STATUS_RUNNING,
                      STATUS_DONE,
                      STATUS_FAILED]:
        raise IncorrectJobStatusException
    with db.engine.begin() as connection:
        connection.execute(
            "UPDATE dataset_eval_jobs "
            "SET (status, status_msg, updated) = (%s, %s, current_timestamp) "
            "WHERE id = %s",
            (status, status_msg, job_id)
        )


def _create_job(connection, dataset_id):
    result = connection.execute(
        "INSERT INTO dataset_eval_jobs (id, dataset_id, status) "
        "VALUES (uuid_generate_v4(), %s, %s) RETURNING id",
        (dataset_id, STATUS_PENDING)
    )
    job_id = result.fetchone()[0]
    return job_id


class IncorrectJobStatusException(db.exceptions.DatabaseException):
    pass

class JobExistsException(db.exceptions.DatabaseException):
    """Should be raised when trying to add a job for dataset that already has one."""
    pass
