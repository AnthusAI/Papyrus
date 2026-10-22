# Score combination simulation output

Seed 20261022. 70 real Shipped items; editor composite mean 3.54, sd 0.28, range 2.62 to 4.12. Scores are base scores before time decay.


## S1. Rank stability (honest readers who agree with editors, about 8 ratings per item, 200 trials)

| option | split_spearman | top10_overlap | spearman_vs_editor | spearman_vs_truth |
|---|---|---|---|---|
| A | 0.921 | 0.804 | 0.92 | 0.916 |
| B5 | 0.89 | 0.742 | 0.883 | 0.918 |
| B10 | 0.937 | 0.834 | 0.93 | 0.92 |
| B20 | 0.97 | 0.911 | 0.962 | 0.909 |
| B40 | 0.985 | 0.946 | 0.975 | 0.895 |
| B20cap.4 | 0.971 | 0.911 | 0.962 | 0.909 |
| C-Front | 1.0 | 1.0 | 1.0 | 0.847 |
| C-Readers | 0.76 | 0.562 | 0.746 | 0.865 |
| D | 0.165 | 0.229 | 0.331 | 0.387 |


## S2. Responsiveness to genuine disagreement (10 items where readers differ by 1.5; 100 trials)

| honest_raters_per_item | option | gap_closure | spearman_vs_reader_truth | spearman_vs_editor | top10_hit_vs_truth |
|---|---|---|---|---|---|
| 2 | A | 0.021 | 0.692 | 0.985 | 0.531 |
| 2 | B5 | 0.228 | 0.855 | 0.85 | 0.643 |
| 2 | B10 | 0.138 | 0.816 | 0.923 | 0.597 |
| 2 | B20 | 0.077 | 0.77 | 0.96 | 0.555 |
| 2 | B40 | 0.041 | 0.736 | 0.975 | 0.536 |
| 2 | B20cap.4 | 0.077 | 0.77 | 0.96 | 0.555 |
| 2 | C-Front | 0.0 | 0.678 | 1.0 | 0.521 |
| 2 | C-Readers | 0.18 | 0.598 | 0.368 | 0.598 |
| 2 | D | n/a | 0.525 | 0.259 | 0.513 |
| 5 | A | 0.25 | 0.834 | 0.843 | 0.687 |
| 5 | B5 | 0.423 | 0.925 | 0.745 | 0.778 |
| 5 | B10 | 0.285 | 0.905 | 0.835 | 0.718 |
| 5 | B20 | 0.174 | 0.858 | 0.912 | 0.647 |
| 5 | B40 | 0.098 | 0.8 | 0.955 | 0.597 |
| 5 | B20cap.4 | 0.174 | 0.858 | 0.912 | 0.646 |
| 5 | C-Front | 0.0 | 0.684 | 1.0 | 0.552 |
| 5 | C-Readers | 0.282 | 0.849 | 0.543 | 0.728 |
| 5 | D | n/a | 0.549 | 0.293 | 0.503 |
| 10 | A | 0.427 | 0.948 | 0.762 | 0.824 |
| 10 | B5 | 0.573 | 0.954 | 0.705 | 0.844 |
| 10 | B10 | 0.429 | 0.952 | 0.765 | 0.816 |
| 10 | B20 | 0.287 | 0.925 | 0.847 | 0.729 |
| 10 | B40 | 0.174 | 0.872 | 0.916 | 0.642 |
| 10 | B20cap.4 | 0.283 | 0.924 | 0.85 | 0.725 |
| 10 | C-Front | 0.0 | 0.693 | 1.0 | 0.541 |
| 10 | C-Readers | 0.424 | 0.923 | 0.616 | 0.785 |
| 10 | D | n/a | 0.537 | 0.298 | 0.485 |
| 30 | A | 0.444 | 0.97 | 0.764 | 0.855 |
| 30 | B5 | 0.758 | 0.975 | 0.68 | 0.901 |
| 30 | B10 | 0.662 | 0.977 | 0.699 | 0.902 |
| 30 | B20 | 0.529 | 0.976 | 0.734 | 0.876 |
| 30 | B40 | 0.378 | 0.959 | 0.798 | 0.805 |
| 30 | B20cap.4 | 0.355 | 0.956 | 0.809 | 0.793 |
| 30 | C-Front | 0.0 | 0.686 | 1.0 | 0.553 |
| 30 | C-Readers | 0.66 | 0.969 | 0.656 | 0.885 |
| 30 | D | n/a | 0.557 | 0.308 | 0.501 |


## S1b. Sensitivity of option D to the assumed upvote behaviour

| median_views_per_item | upvote_rate_slope | D_split_spearman | D_spearman_vs_editor |
|---|---|---|---|
| 120 | 0.06 | 0.161 | 0.338 |
| 120 | 0.15 | 0.403 | 0.522 |
| 500 | 0.06 | 0.392 | 0.538 |
| 500 | 0.15 | 0.692 | 0.712 |
| 2000 | 0.06 | 0.694 | 0.706 |
| 2000 | 0.15 | 0.891 | 0.804 |


## S3. Brigade: socks giving 5 on every dimension plus an upvote (40 trials)

| target_editor_rank | sock_weight | option | socks_to_top5_median | rank_at_20_socks_median | score_gain_at_20_socks |
|---|---|---|---|---|---|
| 35 | full weight | A | 13 | 3 | 0.54 |
| 35 | full weight | B5 | 6 | 1 | 0.92 |
| 35 | full weight | B10 | 8 | 1 | 0.8 |
| 35 | full weight | B20 | 13 | 1 | 0.63 |
| 35 | full weight | B40 | 23 | 7 | 0.44 |
| 35 | full weight | B20cap.4 | 28 | 7 | 0.43 |
| 35 | full weight | C-Front | >300 | 35 | 0.0 |
| 35 | full weight | C-Readers | 3 | 1 | 0.8 |
| 35 | full weight | D | 10 | 1 | 0.41 |
| 35 | 1/3 weight (new account) | A | 40 | 11 | 0.37 |
| 35 | 1/3 weight (new account) | B5 | 18 | 4 | 0.54 |
| 35 | 1/3 weight (new account) | B10 | 25 | 8 | 0.42 |
| 35 | 1/3 weight (new account) | B20 | 40 | 13 | 0.3 |
| 35 | 1/3 weight (new account) | B40 | 70 | 21 | 0.19 |
| 35 | 1/3 weight (new account) | B20cap.4 | 96 | 14 | 0.29 |
| 35 | 1/3 weight (new account) | C-Front | >300 | 35 | 0.0 |
| 35 | 1/3 weight (new account) | C-Readers | 9 | 1 | 0.43 |
| 35 | 1/3 weight (new account) | D | 25 | 8 | 0.13 |
| 10 | full weight | A | 2 | 1 | 0.41 |
| 10 | full weight | B5 | 2 | 1 | 0.68 |
| 10 | full weight | B10 | 2 | 1 | 0.59 |
| 10 | full weight | B20 | 4 | 1 | 0.47 |
| 10 | full weight | B40 | 6 | 1 | 0.33 |
| 10 | full weight | B20cap.4 | 4 | 1 | 0.32 |
| 10 | full weight | C-Front | >300 | 10 | 0.0 |
| 10 | full weight | C-Readers | 1 | 1 | 0.7 |
| 10 | full weight | D | 7 | 1 | 0.43 |
| 10 | 1/3 weight (new account) | A | 6 | 1 | 0.27 |
| 10 | 1/3 weight (new account) | B5 | 4 | 1 | 0.4 |
| 10 | 1/3 weight (new account) | B10 | 6 | 1 | 0.32 |
| 10 | 1/3 weight (new account) | B20 | 10 | 1 | 0.22 |
| 10 | 1/3 weight (new account) | B40 | 17 | 3 | 0.14 |
| 10 | 1/3 weight (new account) | B20cap.4 | 10 | 2 | 0.22 |
| 10 | 1/3 weight (new account) | C-Front | >300 | 10 | 0.0 |
| 10 | 1/3 weight (new account) | C-Readers | 3 | 1 | 0.38 |
| 10 | 1/3 weight (new account) | D | 22 | 7 | 0.2 |


## S3b. Reverse brigade: 20 socks give the editor's top item 1 on every dimension

| option | rank_of_top_item_after_20_downvote_socks_full | rank_after_20_socks_third_weight |
|---|---|---|
| A | 67 | 52 |
| B5 | 70 | 67 |
| B10 | 70 | 62 |
| B20 | 69 | 39 |
| B40 | 64 | 18 |
| B20cap.4 | 63 | 35 |
| C-Front | 1 | 1 |
| C-Readers | 70 | 70 |
| D | 23 | 13 |


## S4. Cold start: one or two ratings per item (200 trials)

| option | mean_abs_rank_shift_vs_editor | mean_abs_score_shift_vs_editor | spearman_vs_editor | rank_jump_when_5th_rating_arrives | score_jump_when_5th_rating_arrives |
|---|---|---|---|---|---|
| A | 0.0 | 0.0 | 1.0 | 7.31 | 0.093 |
| B5 | 17.846 | 0.499 | 0.381 | 2.195 | 0.034 |
| B10 | 14.344 | 0.283 | 0.582 | 1.585 | 0.023 |
| B20 | 9.99 | 0.152 | 0.784 | 1.195 | 0.014 |
| B40 | 5.999 | 0.079 | 0.917 | 1.08 | 0.008 |
| B20cap.4 | 9.99 | 0.152 | 0.784 | 1.195 | 0.014 |
| C-Front | 0.0 | 0.0 | 1.0 | 0.0 | 0.0 |
| C-Readers | 21.935 | 0.45 | 0.102 | 0.0 | 0.073 |
| D | 21.564 | n/a | 0.131 | 0.0 | n/a |


## S5. Popular but overhyped item (100 trials)

| case | option | median_rank_of_overhyped_item | reader_hype_gap_median |
|---|---|---|---|
| editor saw through it | A | 60 | 2.17 |
| editor saw through it | B5 | 61 | 2.17 |
| editor saw through it | B10 | 60 | 2.17 |
| editor saw through it | B20 | 59 | 2.17 |
| editor saw through it | B40 | 58 | 2.17 |
| editor saw through it | B20cap.4 | 59 | 2.17 |
| editor saw through it | C-Front | 54 | 2.17 |
| editor saw through it | C-Readers | 62 | 2.17 |
| editor saw through it | D | 1 | 2.17 |
| editor fooled | A | 20 | 2.18 |
| editor fooled | B5 | 33 | 2.18 |
| editor fooled | B10 | 15 | 2.18 |
| editor fooled | B20 | 7 | 2.18 |
| editor fooled | B40 | 2 | 2.18 |
| editor fooled | B20cap.4 | 7 | 2.18 |
| editor fooled | C-Front | 1 | 2.18 |
| editor fooled | C-Readers | 63 | 2.18 |
| editor fooled | D | 1 | 2.18 |


## Rising: socks to reach the top 5 of the 6-hour window (100 trials)

| rising_rule | sock_weight | socks_to_top5_median |
|---|---|---|
| raw count (current) | full | 3 |
| raw count (current) | third | 6 |
| Wilson on window | full | 2 |
| Wilson on window | third | 6 |
