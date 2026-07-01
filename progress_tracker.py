import time

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)


def _format_duration(seconds):
    seconds = int(seconds)
    minutes, secs = divmod(seconds, 60)
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


class ProgressTracker:
    """Live terminal progress for batch scraping with elapsed time and ETA."""

    def __init__(self):
        self.console = Console()
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self.console,
            transient=False,
        )
        self._task_id = None
        self._batch_start = None
        self._post_start = None
        self._total_posts = 0
        self._post_index = 0
        self._post_stats = []
        self._current_post_id = None
        self._reply_total = 0

    def __enter__(self):
        self.progress.start()
        self._batch_start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.progress.stop()
        return False

    def _description(self, phase):
        return f"Post {self._post_index}/{self._total_posts} · {phase}"

    def _update(self, phase, *, completed=None, total=None):
        if self._task_id is None:
            return
        kwargs = {"description": self._description(phase)}
        if completed is not None:
            kwargs["completed"] = completed
        if total is not None:
            kwargs["total"] = total
        self.progress.update(self._task_id, **kwargs)

    def start_batch(self, total_posts):
        self._total_posts = total_posts
        self._task_id = self.progress.add_task("Starting batch...", total=None)

    def start_post(self, index, url):
        self._post_index = index
        self._post_start = time.perf_counter()
        self._current_post_id = None
        short_url = url if len(url) <= 50 else url[:47] + "..."
        self._update(f"starting ({short_url})")

    def set_phase(self, label):
        self._update(label)

    def set_post_id(self, post_id):
        self._current_post_id = post_id

    def start_comments(self):
        self._update("fetching comments", completed=0, total=None)

    def update_comments_page(self, page, count):
        self._update(f"fetching comments (page {page}, {count} so far)")

    def comments_attempt(self, attempt, total_attempts, count):
        self._update(f"comments attempt {attempt}/{total_attempts} ({count} so far)")

    def finish_comments(self, total):
        self._update(f"fetched {total} comments", completed=0, total=None)

    def start_replies(self, total):
        self._reply_total = total
        self._update("fetching replies", completed=0, total=total or 1)

    def update_replies(self, done, total):
        self._update("fetching replies", completed=done, total=total or 1)

    def finish_post(self, comment_count, reply_count):
        elapsed = time.perf_counter() - self._post_start
        self._post_stats.append({
            "post_id": self._current_post_id or "?",
            "comments": comment_count,
            "replies": reply_count,
            "elapsed": elapsed,
        })

    def finish_batch(self, succeeded, failed, output_file=None):
        if self._task_id is not None:
            self.progress.update(
                self._task_id,
                description="Batch complete",
                completed=1,
                total=1,
            )

        total_elapsed = time.perf_counter() - self._batch_start
        self.console.print()
        self.console.print(
            f"[bold green]Batch complete in {_format_duration(total_elapsed)}[/bold green]"
            f" — {succeeded} succeeded, {failed} failed"
        )
        for stat in self._post_stats:
            self.console.print(
                f"  Post {stat['post_id']}: {stat['comments']} comments, "
                f"{stat['replies']} replies — {_format_duration(stat['elapsed'])}"
            )
        if output_file:
            self.console.print(f"  Output: {output_file}")
