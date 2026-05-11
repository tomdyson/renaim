from photo_renamer.harmonize import harmonize_groups, slug_similarity


def test_slug_similarity_groups_live_music_variants():
    assert slug_similarity("live-music-performance", "live-band-performance") >= 0.4
    assert slug_similarity("live-music-performance", "band-playing-live-music") >= 0.4


def test_harmonize_groups_selects_most_common_canonical_label():
    groups = harmonize_groups(
        [
            "live-music-performance",
            "live-music-performance",
            "live-band-performance",
            "band-playing-live-music",
            "woman-playing-electric-guitar",
        ],
        threshold=0.4,
    )

    assert len(groups) == 1
    assert groups[0].canonical == "live-music-performance"
    assert groups[0].slugs == (
        "band-playing-live-music",
        "live-band-performance",
        "live-music-performance",
    )
