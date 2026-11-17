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
      "recall_at_20": 0.10088440353713633,
      "ndcg_at_20": 0.2512569589882907,
      "precision_at_20": 0.22093999999999842,
      "hit_rate_at_20": 0.8018
    }
  },
  "title_tagged_queries": {
    "popularity": {
      "recall_at_20": 0.014718979502355166,
      "ndcg_at_20": 0.04421606316745567,
      "precision_at_20": 0.04254185692541861,
      "hit_rate_at_20": 0.3165905631659056
    },
    "collaborative_filtering": {
      "recall_at_20": 0.0818586427627245,
      "ndcg_at_20": 0.20355228591096058,
      "precision_at_20": 0.18044140030441375,
      "hit_rate_at_20": 0.7899543378995434
    },
    "selected_tag_ranker": {
      "recall_at_20": 0.08677534743828773,
      "ndcg_at_20": 0.2157151715875814,
      "precision_at_20": 0.18926940639269374,
      "hit_rate_at_20": 0.8051750380517504
    }
  },
  "sample": {
    "eligible_queries_evaluated": 5000,
    "title_tagged_queries": 657,
    "all_seeds_unseen_in_training": 7,
    "unseen_reference_occurrences": 5922,
    "all_reference_occurrences": 316437,
    "sample_seed": 338,
    "sampled_pid_sha256": "3c4e127fde20e90c07056894c92cd8448861c885662e6686abcfd7c4f0efafb3"
  },
  "selected_tag_weight": 1.0,
  "freeze_sha256": "eafaf74516ea8e0e2fbc5ae0aadc1bee991379e2adc06673fd430a07c1ca633c",
  "tag_ranker_minus_cf_ndcg_95_ci_all": [
    0.0010748483594744918,
    0.0021217275223743897
  ],
  "tag_ranker_minus_cf_ndcg_95_ci_tagged": [
    0.008081468502719307,
    0.01600316783783812
  ],
  "title_fit": {
    "titles": 804485,
    "labels": "weak title rules",
    "validation_titles": 5000,
    "validation_rule_macro_f1": 0.9996626180836707
  },
  "weight_validation": {
    "queries": 5000,
    "tagged_queries": 602,
    "scores": {
      "0": {
        "all_queries": 0.2487160276782386,
        "title_tagged_queries": 0.21421679193675264
      },
      "0.25": {
        "all_queries": 0.24907398287771298,
        "title_tagged_queries": 0.21718984176627293
      },
      "0.5": {
        "all_queries": 0.2493816307785513,
        "title_tagged_queries": 0.2197450568895154
      },
      "1": {
        "all_queries": 0.24944677868353732,
        "title_tagged_queries": 0.22028615244588176
      },
      "2": {
        "all_queries": 0.24930652272008982,
        "title_tagged_queries": 0.21912123580594903
      }
    }
  }
};
