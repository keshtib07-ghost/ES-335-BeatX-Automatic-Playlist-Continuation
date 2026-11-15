window.NEXT_TRACK_EXPERIMENT = {
  "all_queries": {
    "popularity": {
      "recall_at_20": 0.012057681910460076,
      "ndcg_at_20": 0.037226589492663276,
      "precision_at_20": 0.03455000000000012,
      "hit_rate_at_20": 0.245
    },
    "collaborative_filtering": {
      "recall_at_20": 0.10023834854276734,
      "ndcg_at_20": 0.24965875581038285,
      "precision_at_20": 0.2197799999999985,
      "hit_rate_at_20": 0.7998
    },
    "selected_tag_ranker": {
      "recall_at_20": 0.10090442945859122,
      "ndcg_at_20": 0.251313234808854,
      "precision_at_20": 0.22099999999999845,
      "hit_rate_at_20": 0.8018
    }
  },
  "title_tagged_queries": {
    "popularity": {
      "recall_at_20": 0.014748213031872145,
      "ndcg_at_20": 0.0444922313179367,
      "precision_at_20": 0.042727272727272766,
      "hit_rate_at_20": 0.3196969696969697
    },
    "collaborative_filtering": {
      "recall_at_20": 0.08178530142508562,
      "ndcg_at_20": 0.20408787493969052,
      "precision_at_20": 0.18090909090909063,
      "hit_rate_at_20": 0.7893939393939394
    },
    "selected_tag_ranker": {
      "recall_at_20": 0.08683136896920593,
      "ndcg_at_20": 0.21662180674629045,
      "precision_at_20": 0.19015151515151488,
      "hit_rate_at_20": 0.8045454545454546
    }
  },
  "sample": {
    "eligible_queries_evaluated": 5000,
    "title_tagged_queries": 660,
    "all_seeds_unseen_in_training": 7,
    "unseen_reference_occurrences": 5922,
    "all_reference_occurrences": 316437
  },
  "selected_tag_weight": 1.0,
  "tag_ranker_minus_cf_ndcg_95_ci_all": [
    0.0011161861076569859,
    0.0021748983104547706
  ],
  "tag_ranker_minus_cf_ndcg_95_ci_tagged": [
    0.008863769820009698,
    0.016464924583855334
  ]
};
