window.BEATX_RESEARCH_ADDITIONS = {
  "eda": {
    "schema_version": 1,
    "kind": "verified_training_pilot_eda",
    "scope": "All 20,000 playlists in the original pinned training pilot. These slices were forced into training. This is a descriptive subset, not an estimate of the full MPD distribution.",
    "source": {
      "repository": "https://github.com/DevinOgrady/spotify_million_playlist_dataset",
      "commit": "63a10af75e411955f44f8e373dcafadcaf3f3e9a",
      "git_blob_sha1": {
        "mpd.slice.0-999.json": "b5af2506b31f79342b6ed12579167281a4ed9d87",
        "mpd.slice.1000-1999.json": "eb0b47bb1257e7a0b12248400a4bdfe71a92a6f8",
        "mpd.slice.114000-114999.json": "e758a9d45ba2ebe6476d12f4f007dad341b54f02",
        "mpd.slice.216000-216999.json": "c355b9992fe46de7c171bf9c7ff08f8ea2e2d933",
        "mpd.slice.22000-22999.json": "72a066a852a31adeb23d3bfecc64b8c14a1ec03f",
        "mpd.slice.3000-3999.json": "63a856de18bfc6e9a233a113285cb9c0f465ff8b",
        "mpd.slice.38000-38999.json": "92fc2d9ca4f05473a2d0a5b0d83d6e61fa60c08a",
        "mpd.slice.43000-43999.json": "9c646cc16ee497c486a06b7cb43cdee7947e915d",
        "mpd.slice.45000-45999.json": "02cc57340c50c83b2dc108e219133038461bd4fb",
        "mpd.slice.47000-47999.json": "593803c410ce1ecd54fa94ad1f5f4111b27d3115",
        "mpd.slice.49000-49999.json": "d2b164f545b91b702c64c794b1e1fcdacae5bfe5",
        "mpd.slice.62000-62999.json": "1c1af8260aee0d1bb6e5e370fbb58a9430d425b9",
        "mpd.slice.64000-64999.json": "77c62a20a57985267bcb5ebd199ec13ec625f732",
        "mpd.slice.66000-66999.json": "c393f5f0f218125bc0fe1fe70223b22ee6c6438e",
        "mpd.slice.68000-68999.json": "02139fdd46ed8ed64238ca24ad53f01a1b820924",
        "mpd.slice.7000-7999.json": "5fd29de99babbdb77d049af1ff881b9beca08dc1",
        "mpd.slice.70000-70999.json": "5f1f375899a26efe509f6e9f0c72fd8fd243d52f",
        "mpd.slice.72000-72999.json": "2364f5515a76655b5b5f045523674d002f7b8456",
        "mpd.slice.74000-74999.json": "4111e9b4b7f3d14c6baf7cd728ea8733943c9b94",
        "mpd.slice.75000-75999.json": "8ca9b9e65d9a74bb8b1634b838b28145c6a0ef87"
      }
    },
    "playlists": 20000,
    "raw_occurrences": 1345066,
    "repeat_occurrences_removed": 18469,
    "invalid_occurrences": 0,
    "all_playlists": {
      "playlist_length": {
        "labels": [
          "0\u20139",
          "10\u201319",
          "20\u201339",
          "40\u201359",
          "60\u201399",
          "100\u2013149",
          "150\u2013199",
          "200\u2013299",
          "300+"
        ],
        "counts": [
          696,
          2522,
          4929,
          3401,
          4038,
          2504,
          1225,
          685,
          0
        ],
        "total": 20000
      },
      "track_support": {
        "labels": [
          "0\u20130",
          "1\u20131",
          "2\u20134",
          "5\u20139",
          "10\u201319",
          "20\u201349",
          "50\u201399",
          "100\u2013999",
          "1000\u20139999",
          "10000\u2013999999",
          "1000000+"
        ],
        "counts": [
          0,
          165710,
          63636,
          18899,
          9769,
          6354,
          2397,
          2010,
          0,
          0,
          0
        ],
        "total": 268775
      },
      "title_length": {
        "labels": [
          "0\u20130",
          "1\u20134",
          "5\u20139",
          "10\u201319",
          "20\u201339",
          "40\u201379",
          "80+"
        ],
        "counts": [
          0,
          4547,
          10045,
          5238,
          154,
          16,
          0
        ],
        "total": 20000
      },
      "duplicate_group_size": {
        "labels": [
          "1\u20131",
          "2\u20132",
          "3\u20134",
          "5\u20139",
          "10\u201319",
          "20\u201349",
          "50+"
        ],
        "counts": [
          19974,
          4,
          4,
          1,
          0,
          0,
          0
        ],
        "total": 19983
      },
      "playlist_length_quantiles": {
        "min": 4.0,
        "q25": 26.0,
        "median": 50.0,
        "q75": 92.0,
        "max": 250.0
      },
      "distinct_tracks": 268775,
      "memberships": 1326597,
      "top_one_percent_membership_share": 0.3353957531940748,
      "singleton_tracks": 165710,
      "empty_titles": 0,
      "non_ascii_titles": 427,
      "extra_exact_group_members": 17,
      "text_note": "Character/script summaries are not language identification."
    },
    "metadata": {
      "bpm_in_raw_mpd": false,
      "bass_in_raw_mpd": false,
      "note": "Raw MPD does not provide verified BPM or spectral bass. Enrichment coverage needs a separate source-backed audit."
    }
  },
  "studio_audit": {
    "schema_version": 1,
    "kind": "live_functional_audit",
    "measured_utc": "2026-11-17T16:25:40.398698+00:00",
    "api": "https://beatx-api-keshav.centralindia.cloudapp.azure.com",
    "model_id": "eafaf74516ea8e0e2fbc5ae0aadc1bee991379e2adc06673fd430a07c1ca633c",
    "cases": [
      {
        "case": "title_only_study",
        "request": {
          "title": "Rainy Night Study",
          "seeds": [],
          "method": "unified",
          "filters": {}
        },
        "http_status": 200,
        "expected_http_status": 200,
        "results": 20,
        "known_seeds": 0,
        "applied_context": [
          "rainy",
          "study_focus"
        ],
        "note": "No seed co-occurrence evidence. Used title or selected context with training popularity.",
        "artist_diversity": 0.85,
        "largest_artist_share": 0.15,
        "known_bpm_results": 16,
        "seconds": 8.209,
        "checks": {
          "expected_http_status": true,
          "no_duplicate_track_ids": true,
          "seeds_excluded": true,
          "at_most_20": true,
          "uses_unified_method": true
        },
        "ranking_sha256": "bd123a227c4005b8c15218d45ac83d3831cc0df048b6d6d049044cd37f2071b5"
      },
      {
        "case": "title_only_gym",
        "request": {
          "title": "Gym workout",
          "seeds": [],
          "method": "unified",
          "filters": {}
        },
        "http_status": 200,
        "expected_http_status": 200,
        "results": 20,
        "known_seeds": 0,
        "applied_context": [
          "gym"
        ],
        "note": "No seed co-occurrence evidence. Used title or selected context with training popularity.",
        "artist_diversity": 0.8,
        "largest_artist_share": 0.15,
        "known_bpm_results": 19,
        "seconds": 8.224,
        "checks": {
          "expected_http_status": true,
          "no_duplicate_track_ids": true,
          "seeds_excluded": true,
          "at_most_20": true,
          "uses_unified_method": true
        },
        "ranking_sha256": "78451f7d3ac237c6fca0a4c36c3036345176dfeef5a1adae53352e6a3f92380e"
      },
      {
        "case": "no_context",
        "request": {
          "title": "My playlist",
          "seeds": [],
          "method": "unified",
          "filters": {}
        },
        "http_status": 200,
        "expected_http_status": 200,
        "results": 20,
        "known_seeds": 0,
        "applied_context": [],
        "note": "No usable seed or context evidence. Used training popularity.",
        "artist_diversity": 0.85,
        "largest_artist_share": 0.15,
        "known_bpm_results": 19,
        "seconds": 7.818,
        "checks": {
          "expected_http_status": true,
          "no_duplicate_track_ids": true,
          "seeds_excluded": true,
          "at_most_20": true,
          "uses_unified_method": true
        },
        "ranking_sha256": "0dfd4f4e9608892c44c332117f93781cb88fff95d5c1065000db6faba84dd14b"
      },
      {
        "case": "unknown_seed",
        "request": {
          "title": "Gym workout",
          "seeds": [
            "ZZZZZZZZZZZZZZZZZZZZZZ"
          ],
          "method": "unified",
          "filters": {}
        },
        "http_status": 200,
        "expected_http_status": 200,
        "results": 20,
        "known_seeds": 0,
        "applied_context": [
          "gym"
        ],
        "note": "1 seed(s) outside the model catalogue. No seed co-occurrence evidence. Used title or selected context with training popularity.",
        "artist_diversity": 0.8,
        "largest_artist_share": 0.15,
        "known_bpm_results": 19,
        "seconds": 8.165,
        "checks": {
          "expected_http_status": true,
          "no_duplicate_track_ids": true,
          "seeds_excluded": true,
          "at_most_20": true,
          "uses_unified_method": true
        },
        "ranking_sha256": "78451f7d3ac237c6fca0a4c36c3036345176dfeef5a1adae53352e6a3f92380e"
      },
      {
        "case": "mixed_seeds",
        "request": {
          "title": "Study focus",
          "seeds": [
            "7fnqltLx83HsYLQajzCYRk",
            "ZZZZZZZZZZZZZZZZZZZZZZ"
          ],
          "method": "unified",
          "filters": {}
        },
        "http_status": 200,
        "expected_http_status": 200,
        "results": 20,
        "known_seeds": 1,
        "applied_context": [
          "chill",
          "rainy",
          "romantic",
          "sad",
          "study_focus"
        ],
        "note": "1 seed(s) outside the model catalogue.",
        "artist_diversity": 0.45,
        "largest_artist_share": 0.35,
        "known_bpm_results": 11,
        "seconds": 8.151,
        "checks": {
          "expected_http_status": true,
          "no_duplicate_track_ids": true,
          "seeds_excluded": true,
          "at_most_20": true,
          "uses_unified_method": true
        },
        "ranking_sha256": "ac46d1d93db410e4eac560103527e16bc28182aa21340f584e549daf489f4abd"
      },
      {
        "case": "known_study",
        "request": {
          "title": "Study focus",
          "seeds": [
            "7fnqltLx83HsYLQajzCYRk",
            "3YYKrn3iGOAel605Znt3ai",
            "64fGW0tyU2caV8ddFLUUBj"
          ],
          "method": "unified",
          "filters": {}
        },
        "http_status": 200,
        "expected_http_status": 200,
        "results": 20,
        "known_seeds": 3,
        "applied_context": [
          "chill",
          "rainy",
          "romantic",
          "sad",
          "study_focus"
        ],
        "note": "",
        "artist_diversity": 0.7,
        "largest_artist_share": 0.2,
        "known_bpm_results": 12,
        "seconds": 6.367,
        "checks": {
          "expected_http_status": true,
          "no_duplicate_track_ids": true,
          "seeds_excluded": true,
          "at_most_20": true,
          "uses_unified_method": true
        },
        "ranking_sha256": "378d26c148f1043d256e9223594d54ad741ba8cea408936f1e0333915fa0931f"
      },
      {
        "case": "conflicting_title",
        "request": {
          "title": "Gym workout",
          "seeds": [
            "7fnqltLx83HsYLQajzCYRk",
            "3YYKrn3iGOAel605Znt3ai",
            "64fGW0tyU2caV8ddFLUUBj"
          ],
          "method": "unified",
          "filters": {}
        },
        "http_status": 200,
        "expected_http_status": 200,
        "results": 20,
        "known_seeds": 3,
        "applied_context": [
          "chill",
          "gym",
          "rainy",
          "romantic",
          "sad"
        ],
        "note": "Title took priority over conflicting seeds tags.",
        "artist_diversity": 0.7,
        "largest_artist_share": 0.2,
        "known_bpm_results": 12,
        "seconds": 7.826,
        "checks": {
          "expected_http_status": true,
          "no_duplicate_track_ids": true,
          "seeds_excluded": true,
          "at_most_20": true,
          "uses_unified_method": true
        },
        "ranking_sha256": "bc3d56459c9834f9356c07063a49ae952169c2adf496d1f90265ba93889b842c"
      },
      {
        "case": "explicit_gym",
        "request": {
          "title": "Gym workout",
          "seeds": [
            "7fnqltLx83HsYLQajzCYRk",
            "3YYKrn3iGOAel605Znt3ai",
            "64fGW0tyU2caV8ddFLUUBj"
          ],
          "method": "unified",
          "filters": {
            "tags": [
              "gym"
            ]
          }
        },
        "http_status": 200,
        "expected_http_status": 200,
        "results": 20,
        "known_seeds": 3,
        "applied_context": [
          "chill",
          "gym",
          "rainy",
          "romantic",
          "sad"
        ],
        "note": "Title took priority over conflicting seeds tags.",
        "artist_diversity": 0.65,
        "largest_artist_share": 0.25,
        "known_bpm_results": 15,
        "seconds": 8.198,
        "checks": {
          "expected_http_status": true,
          "no_duplicate_track_ids": true,
          "seeds_excluded": true,
          "at_most_20": true,
          "uses_unified_method": true
        },
        "ranking_sha256": "bd80a28641767523ceedd154627526d2a98934aca25c22d4368909dcd8b0753e"
      },
      {
        "case": "explicit_conflict",
        "request": {
          "title": "Gym workout",
          "seeds": [
            "7fnqltLx83HsYLQajzCYRk",
            "3YYKrn3iGOAel605Znt3ai",
            "64fGW0tyU2caV8ddFLUUBj"
          ],
          "method": "unified",
          "filters": {
            "tags": [
              "study_focus"
            ]
          }
        },
        "http_status": 200,
        "expected_http_status": 200,
        "results": 20,
        "known_seeds": 3,
        "applied_context": [
          "chill",
          "gym",
          "rainy",
          "romantic",
          "sad",
          "study_focus"
        ],
        "note": "Title took priority over conflicting seeds tags.",
        "artist_diversity": 0.7,
        "largest_artist_share": 0.2,
        "known_bpm_results": 12,
        "seconds": 7.988,
        "checks": {
          "expected_http_status": true,
          "no_duplicate_track_ids": true,
          "seeds_excluded": true,
          "at_most_20": true,
          "uses_unified_method": true
        },
        "ranking_sha256": "bc3d56459c9834f9356c07063a49ae952169c2adf496d1f90265ba93889b842c"
      },
      {
        "case": "restrictive_tempo",
        "request": {
          "title": "Study focus",
          "seeds": [
            "7fnqltLx83HsYLQajzCYRk",
            "3YYKrn3iGOAel605Znt3ai",
            "64fGW0tyU2caV8ddFLUUBj"
          ],
          "method": "unified",
          "filters": {
            "min_bpm": 299,
            "max_bpm": 300
          }
        },
        "http_status": 200,
        "expected_http_status": 200,
        "results": 0,
        "known_seeds": 3,
        "applied_context": [
          "chill",
          "rainy",
          "romantic",
          "sad",
          "study_focus"
        ],
        "note": "BPM filters require a known tempo. Fewer than 20 songs matched the active filters and context.",
        "artist_diversity": null,
        "largest_artist_share": null,
        "known_bpm_results": 0,
        "seconds": 9.611,
        "checks": {
          "expected_http_status": true,
          "no_duplicate_track_ids": true,
          "seeds_excluded": true,
          "at_most_20": true,
          "uses_unified_method": true
        },
        "ranking_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
      },
      {
        "case": "duplicate_seeds",
        "request": {
          "title": "Study focus",
          "seeds": [
            "7fnqltLx83HsYLQajzCYRk",
            "7fnqltLx83HsYLQajzCYRk"
          ],
          "method": "unified",
          "filters": {}
        },
        "http_status": 400,
        "expected_http_status": 400,
        "results": 0,
        "known_seeds": null,
        "applied_context": [],
        "note": "Select distinct Spotify track IDs.",
        "artist_diversity": null,
        "largest_artist_share": null,
        "known_bpm_results": 0,
        "seconds": 8.156,
        "checks": {
          "expected_http_status": true,
          "no_duplicate_track_ids": true,
          "seeds_excluded": true,
          "at_most_20": true
        },
        "ranking_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
      }
    ],
    "comparison": {
      "same_seed_different_title_overlap_at_20": 20,
      "same_seed_different_title_same_order": false
    },
    "all_contract_checks_passed": true,
    "scope": "Prespecified constructed requests against the deployed API. No hidden references or listener judgments. This is not Recall, NDCG or a population failure rate."
  },
  "studio_evaluation": null
};
