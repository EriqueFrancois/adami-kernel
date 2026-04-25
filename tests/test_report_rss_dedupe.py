from adami_kernel.peripheral.report_studio.rss_aggregate import (
    RssEntry,
    _cluster_entries,
    _title_similarity,
)


def test_title_similarity_detects_near_dupes():
    a = "Breaking: floods hit region"
    b = "Breaking: Floods Hit Region — update"
    assert _title_similarity(a, b) >= 0.78


def test_cluster_merges_same_link():
    e1 = RssEntry(
        title="A",
        link="https://example.com/x?utm=1",
        summary="",
        published=None,
        source_name="s1",
        source_url="u1",
    )
    e2 = RssEntry(
        title="A updated",
        link="https://example.com/x",
        summary="",
        published=None,
        source_name="s2",
        source_url="u2",
    )
    clusters = _cluster_entries([e1, e2])
    assert len(clusters) == 1
    assert clusters[0].weight == 2
