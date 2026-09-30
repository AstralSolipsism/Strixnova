# 已复核评价的限定事实与引用纠正

原评价已有独立复核，但登记步骤拒绝了混入数量括注或多个文件的 ref。真实文件在当前冻结包里；问题不应被解释为文件缺失。

本次只核对并修正可定位引用与统计口径，不重跑程序、测试或业务，不修改原记录。请保留原评价历史，重新提交本 packet 同一批目标的完整结构化候选供独立复核。

每个 evidence.ref 请使用一个实际冻结文件加精确行号/测试节点，或现有 packet 中对应目标 test_definition_ids 的明确定位。一个证据项不要把数量、运行说明、多个文件混进 ref；必要时拆成数项。数量与局限放 claim/limitations，不猜文件名或行号。

下方是程序从本轮相同 packet.test_definitions 的 recorded_executions 直接提取的事实。必须区分函数定义数、参数化后的 JUnit 行数、不同运行的 passed/failed/skipped 和按文件分组数量。先前失败和后续成功分别说明，未运行与跳过不能改为通过；数量不必要时可以不写，但真实限制不能省略。不要把未独立保存的执行时源码摘要说成精确版本覆盖。

这些计数只证明所登记执行记录的直接数据，不证明实现或 Agent 语义。若事实更正影响原结论，由你按合同和证据重新判断；不预设 implemented。原独立通过不约束本次判断。所有冻结实现输入和合同未变化。

```json
[
  {
    "target_id": "RELATION-CDC41CEBF40D49A5",
    "definition_count": 19,
    "definition_count_by_file": {
      "tests/integration/test_git_workspace.py": 4,
      "tests/unit/test_application_delivery_snapshots.py": 8,
      "tests/unit/test_host_adapter.py": 4,
      "tests/unit/test_target_architecture_contract.py": 3
    },
    "test_definition_ids": [
      "tests/integration/test_git_workspace.py::test_single_work_item_uses_a_local_branch_without_forcing_a_new_worktree",
      "tests/integration/test_git_workspace.py::test_existing_uncommitted_work_is_never_stashed_or_adopted",
      "tests/integration/test_git_workspace.py::test_linked_worktree_path_must_stay_outside_the_repository",
      "tests/integration/test_git_workspace.py::test_linked_worktree_never_overwrites_an_existing_external_path",
      "tests/unit/test_application_delivery_snapshots.py::test_actual_result_snapshot_rejects_an_added_unplanned_file",
      "tests/unit/test_application_delivery_snapshots.py::test_actual_result_snapshot_rejects_file_swap_before_commit",
      "tests/unit/test_application_delivery_snapshots.py::test_conflict_can_have_no_applicable_retest_command",
      "tests/unit/test_application_delivery_snapshots.py::test_immutable_result_commit_must_equal_the_presented_file_snapshot",
      "tests/unit/test_application_delivery_snapshots.py::test_prepared_in_place_merge_uses_the_target_tip_as_comparison_base",
      "tests/unit/test_application_delivery_snapshots.py::test_slice_completion_rejects_an_omitted_planned_file_operation",
      "tests/unit/test_application_delivery_snapshots.py::test_target_advance_projection_blocks_upstream_authority_pollution_only",
      "tests/unit/test_application_delivery_snapshots.py::test_terminal_failure_does_not_require_a_future_long_lived_artifact",
      "tests/unit/test_host_adapter.py::test_actual_result_accepts_a_planned_long_lived_move",
      "tests/unit/test_host_adapter.py::test_actual_result_accepts_a_removed_long_lived_artifact_only_after_unindexing",
      "tests/unit/test_host_adapter.py::test_actual_result_accepts_a_successor_alignment_over_an_unintegrated_baseline",
      "tests/unit/test_host_adapter.py::test_actual_result_does_not_skip_unplanned_domain_metadata_change",
      "tests/unit/test_target_architecture_contract.py::test_every_mediated_relationship_has_both_declared_direct_legs",
      "tests/unit/test_target_architecture_contract.py::test_target_direct_dependency_graph_is_acyclic_and_default_denied",
      "tests/unit/test_target_architecture_contract.py::test_high_risk_boundaries_are_explicit_in_the_target_graph"
    ],
    "runs": {
      "d0856323c4b6": {
        "recorded_rows": 19,
        "outcome_counts": {
          "passed": 19
        },
        "count_by_file": {
          "tests/integration/test_git_workspace.py": 4,
          "tests/unit/test_application_delivery_snapshots.py": 8,
          "tests/unit/test_host_adapter.py": 4,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      },
      "f5e20647248e": {
        "recorded_rows": 18,
        "outcome_counts": {
          "passed": 18
        },
        "count_by_file": {
          "tests/integration/test_git_workspace.py": 4,
          "tests/unit/test_application_delivery_snapshots.py": 8,
          "tests/unit/test_host_adapter.py": 3,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      }
    },
    "original_test_evidence": [
      {
        "claim": "All 4 integration tests pass across 2 runs confirming local branch, uncommitted-work, worktree path constraints",
        "kind": "test",
        "ref": "tests/integration/test_git_workspace.py (4 tests)"
      },
      {
        "claim": "All 8 delivery snapshot tests pass confirming gate-based invocation",
        "kind": "test",
        "ref": "tests/unit/test_application_delivery_snapshots.py (8 tests)"
      }
    ]
  },
  {
    "target_id": "RELATION-D30AE8CE877C462F",
    "definition_count": 23,
    "definition_count_by_file": {
      "tests/unit/test_project_authority_consistency.py": 4,
      "tests/unit/test_yaml_metadata_patch.py": 4,
      "tests/integration/test_configured_project_context.py": 9,
      "tests/integration/test_local_git_lifecycle.py": 3,
      "tests/unit/test_target_architecture_contract.py": 3
    },
    "test_definition_ids": [
      "tests/unit/test_project_authority_consistency.py::test_immutable_full_authority_chain_uses_one_snapshot_and_bounded_batches",
      "tests/unit/test_project_authority_consistency.py::test_baseline_identity_must_match_the_loaded_authority",
      "tests/unit/test_project_authority_consistency.py::test_confirmed_policy_may_outlive_the_product_revision_it_was_reviewed_against",
      "tests/unit/test_project_authority_consistency.py::test_confirmed_policy_must_still_belong_to_the_same_stable_product",
      "tests/unit/test_yaml_metadata_patch.py::test_patch_yaml_values_changes_only_selected_metadata_spans",
      "tests/unit/test_yaml_metadata_patch.py::test_atomic_replacement_preserves_existing_file_mode",
      "tests/unit/test_yaml_metadata_patch.py::test_yaml_patch_transaction_recovers_after_one_file_was_already_written",
      "tests/unit/test_yaml_metadata_patch.py::test_yaml_patch_transaction_rolls_back_prior_files_when_later_write_fails",
      "tests/integration/test_configured_project_context.py::test_configuration_and_baseline_can_belong_to_different_repositories",
      "tests/integration/test_configured_project_context.py::test_cross_repository_adoption_requires_an_explicit_commit",
      "tests/integration/test_configured_project_context.py::test_existing_item_can_be_cancelled_when_the_current_locator_is_invalid",
      "tests/integration/test_configured_project_context.py::test_governance_profile_reuses_the_policy_repository_and_commit",
      "tests/integration/test_configured_project_context.py::test_multi_repository_execution_requires_an_existing_work_item_before_side_effects",
      "tests/integration/test_configured_project_context.py::test_public_project_status_reads_separated_authorities_without_creating_state",
      "tests/integration/test_configured_project_context.py::test_missing_authority_keeps_pinned_single_repository_metadata_read_only",
      "tests/integration/test_configured_project_context.py::test_split_authorities_use_one_context_and_exact_independent_commits",
      "tests/integration/test_configured_project_context.py::test_unadopted_status_does_not_create_the_configured_management_directory",
      "tests/integration/test_local_git_lifecycle.py::test_add_capability_records_public_interface_and_adr_through_full_lifecycle",
      "tests/integration/test_local_git_lifecycle.py::test_cancel_cleans_only_safe_empty_work_and_preserves_dirty_work",
      "tests/integration/test_local_git_lifecycle.py::test_complete_flow_tests_before_confirmation_then_commits_and_merges",
      "tests/unit/test_target_architecture_contract.py::test_every_mediated_relationship_has_both_declared_direct_legs",
      "tests/unit/test_target_architecture_contract.py::test_target_direct_dependency_graph_is_acyclic_and_default_denied",
      "tests/unit/test_target_architecture_contract.py::test_high_risk_boundaries_are_explicit_in_the_target_graph"
    ],
    "runs": {
      "d0856323c4b6": {
        "recorded_rows": 24,
        "outcome_counts": {
          "passed": 24
        },
        "count_by_file": {
          "tests/unit/test_project_authority_consistency.py": 4,
          "tests/unit/test_yaml_metadata_patch.py": 4,
          "tests/integration/test_configured_project_context.py": 10,
          "tests/integration/test_local_git_lifecycle.py": 3,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      },
      "f5e20647248e": {
        "recorded_rows": 21,
        "outcome_counts": {
          "passed": 21
        },
        "count_by_file": {
          "tests/unit/test_project_authority_consistency.py": 4,
          "tests/unit/test_yaml_metadata_patch.py": 4,
          "tests/integration/test_configured_project_context.py": 10,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      },
      "5bba08870241": {
        "recorded_rows": 4,
        "outcome_counts": {
          "passed": 4
        },
        "count_by_file": {
          "tests/unit/test_project_authority_consistency.py": 4
        },
        "non_passed": []
      },
      "30608175d9f5": {
        "recorded_rows": 2,
        "outcome_counts": {
          "passed": 2
        },
        "count_by_file": {
          "tests/integration/test_configured_project_context.py": 2
        },
        "non_passed": []
      }
    },
    "original_test_evidence": [
      {
        "claim": "All 4 tests pass across 3 runs confirming read-only behavior",
        "kind": "test",
        "ref": "tests/unit/test_project_authority_consistency.py (4 tests)"
      },
      {
        "claim": "All 4 patch tests pass confirming write boundary is in yaml_metadata_patch module itself",
        "kind": "test",
        "ref": "tests/unit/test_yaml_metadata_patch.py (4 tests)"
      }
    ]
  },
  {
    "target_id": "RELATION-D4E5FF14DCD0494C",
    "definition_count": 15,
    "definition_count_by_file": {
      "tests/unit/test_implementation_alignment_preparation.py": 12,
      "tests/unit/test_target_architecture_contract.py": 3
    },
    "test_definition_ids": [
      "tests/unit/test_implementation_alignment_preparation.py::test_single_module_and_root_sources_prepare_without_layout_changes",
      "tests/unit/test_implementation_alignment_preparation.py::test_binding_requires_one_current_alignment_operation",
      "tests/unit/test_implementation_alignment_preparation.py::test_preparation_store_is_content_addressed_without_mutable_pointer",
      "tests/unit/test_implementation_alignment_preparation.py::test_alignment_cli_group_routes_small_structured_requests",
      "tests/unit/test_implementation_alignment_preparation.py::test_alignment_cli_writes_a_schema_valid_nonempty_decision",
      "tests/unit/test_implementation_alignment_preparation.py::test_alignment_gc_requires_exact_preview_and_deletes_only_orphan_components",
      "tests/unit/test_implementation_alignment_preparation.py::test_alignment_inspection_pages_every_logical_record_without_layout_leak",
      "tests/unit/test_implementation_alignment_preparation.py::test_alignment_prepare_cli_reads_the_canonical_authority_store",
      "tests/unit/test_implementation_alignment_preparation.py::test_external_capture_requires_both_authorization_and_a_confirmed_plan",
      "tests/unit/test_implementation_alignment_preparation.py::test_large_preparation_is_a_small_manifest_with_deduplicated_pages",
      "tests/unit/test_implementation_alignment_preparation.py::test_planned_external_provider_can_complete_an_unknown_language_scope",
      "tests/unit/test_implementation_alignment_preparation.py::test_preparation_requires_agent_acknowledgement_for_every_semantic_removal",
      "tests/unit/test_target_architecture_contract.py::test_every_mediated_relationship_has_both_declared_direct_legs",
      "tests/unit/test_target_architecture_contract.py::test_target_direct_dependency_graph_is_acyclic_and_default_denied",
      "tests/unit/test_target_architecture_contract.py::test_high_risk_boundaries_are_explicit_in_the_target_graph"
    ],
    "runs": {
      "d0856323c4b6": {
        "recorded_rows": 15,
        "outcome_counts": {
          "passed": 15
        },
        "count_by_file": {
          "tests/unit/test_implementation_alignment_preparation.py": 12,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      },
      "f5e20647248e": {
        "recorded_rows": 15,
        "outcome_counts": {
          "passed": 15
        },
        "count_by_file": {
          "tests/unit/test_implementation_alignment_preparation.py": 12,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      },
      "5bba08870241": {
        "recorded_rows": 12,
        "outcome_counts": {
          "passed": 12
        },
        "count_by_file": {
          "tests/unit/test_implementation_alignment_preparation.py": 12
        },
        "non_passed": []
      }
    },
    "original_test_evidence": [
      {
        "claim": "All 12 tests pass across 3 runs confirming bounded preparation, content-addressing, gc, cli routing, external capture, semantic removal acknowledgement",
        "kind": "test",
        "ref": "tests/unit/test_implementation_alignment_preparation.py (12 tests)"
      }
    ]
  },
  {
    "target_id": "RELATION-D7C6624612F34880",
    "definition_count": 27,
    "definition_count_by_file": {
      "tests/unit/test_agent_setup.py": 4,
      "tests/unit/test_confirmation_protocol.py": 4,
      "tests/unit/test_current_action.py": 4,
      "tests/integration/test_multi_repository_planning.py": 11,
      "tests/unit/test_bounded_records.py": 1,
      "tests/unit/test_target_architecture_contract.py": 3
    },
    "test_definition_ids": [
      "tests/unit/test_agent_setup.py::test_packaged_agent_skill_has_one_entry_and_reachable_internal_references",
      "tests/unit/test_agent_setup.py::test_product_discovery_guidance_is_optional_and_has_bounded_outcomes",
      "tests/unit/test_agent_setup.py::test_domain_fact_reference_matches_every_runtime_fact_contract",
      "tests/unit/test_agent_setup.py::test_architecture_reference_matches_every_runtime_artifact_contract",
      "tests/unit/test_confirmation_protocol.py::test_challenge_binds_candidate_and_version_without_a_password",
      "tests/unit/test_confirmation_protocol.py::test_explicit_agent_decision_preserves_full_original_message",
      "tests/unit/test_confirmation_protocol.py::test_incomplete_or_undecided_input_cannot_advance",
      "tests/unit/test_confirmation_protocol.py::test_raw_reply_alone_cannot_advance",
      "tests/unit/test_current_action.py::test_current_action_requests_the_pending_receipt_and_its_execution_context",
      "tests/unit/test_current_action.py::test_current_action_names_the_exact_confirmed_command_record",
      "tests/unit/test_current_action.py::test_direction_context_drift_projects_one_recoverable_direction_action",
      "tests/unit/test_current_action.py::test_current_action_guides_missing_upstream_authority_before_slice",
      "tests/integration/test_multi_repository_planning.py::test_domain_fact_location_includes_its_authority_repository",
      "tests/integration/test_multi_repository_planning.py::test_external_repository_is_a_dependency_without_delivery_ownership",
      "tests/integration/test_multi_repository_planning.py::test_invalid_repository_plans_do_not_create_management_state",
      "tests/integration/test_multi_repository_planning.py::test_management_store_rejects_a_second_project_identity",
      "tests/integration/test_multi_repository_planning.py::test_one_plan_distinguishes_equal_paths_and_commands_in_two_repositories",
      "tests/integration/test_multi_repository_planning.py::test_one_selected_repository_uses_the_same_preparation_contract",
      "tests/integration/test_multi_repository_planning.py::test_policy_relative_program_is_resolved_in_its_command_repository",
      "tests/integration/test_multi_repository_planning.py::test_public_cli_intake_uses_explicit_management_root",
      "tests/integration/test_multi_repository_planning.py::test_replanning_changes_responsibilities_and_rejects_the_previous_confirmation",
      "tests/integration/test_multi_repository_planning.py::test_separated_entry_keeps_one_item_and_one_plan_confirmation_then_offers_preparation",
      "tests/integration/test_multi_repository_planning.py::test_verification_input_repositories_are_explicit_and_cannot_omit_the_execution_source",
      "tests/unit/test_bounded_records.py::test_allowed_parent_can_be_read_as_an_exact_child",
      "tests/unit/test_target_architecture_contract.py::test_every_mediated_relationship_has_both_declared_direct_legs",
      "tests/unit/test_target_architecture_contract.py::test_target_direct_dependency_graph_is_acyclic_and_default_denied",
      "tests/unit/test_target_architecture_contract.py::test_high_risk_boundaries_are_explicit_in_the_target_graph"
    ],
    "runs": {
      "d0856323c4b6": {
        "recorded_rows": 38,
        "outcome_counts": {
          "passed": 38
        },
        "count_by_file": {
          "tests/unit/test_agent_setup.py": 4,
          "tests/unit/test_confirmation_protocol.py": 9,
          "tests/unit/test_current_action.py": 4,
          "tests/integration/test_multi_repository_planning.py": 17,
          "tests/unit/test_bounded_records.py": 1,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      },
      "f5e20647248e": {
        "recorded_rows": 38,
        "outcome_counts": {
          "passed": 38
        },
        "count_by_file": {
          "tests/unit/test_agent_setup.py": 4,
          "tests/unit/test_confirmation_protocol.py": 9,
          "tests/unit/test_current_action.py": 4,
          "tests/integration/test_multi_repository_planning.py": 17,
          "tests/unit/test_bounded_records.py": 1,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      }
    },
    "original_test_evidence": [
      {
        "claim": "All related tests pass confirming the mediated path",
        "kind": "test",
        "ref": "tests/unit/test_agent_setup.py (4 tests), tests/unit/test_confirmation_protocol.py (4 tests), tests/unit/test_current_action.py (4 tests)"
      }
    ]
  },
  {
    "target_id": "RELATION-D9A7FFF677B8411B",
    "definition_count": 23,
    "definition_count_by_file": {
      "tests/unit/test_project_authority_consistency.py": 4,
      "tests/unit/test_project_engineering_baseline.py": 4,
      "tests/integration/test_configured_project_context.py": 9,
      "tests/unit/test_host_adapter.py": 3,
      "tests/unit/test_target_architecture_contract.py": 3
    },
    "test_definition_ids": [
      "tests/unit/test_project_authority_consistency.py::test_immutable_full_authority_chain_uses_one_snapshot_and_bounded_batches",
      "tests/unit/test_project_authority_consistency.py::test_baseline_identity_must_match_the_loaded_authority",
      "tests/unit/test_project_authority_consistency.py::test_confirmed_policy_may_outlive_the_product_revision_it_was_reviewed_against",
      "tests/unit/test_project_authority_consistency.py::test_confirmed_policy_must_still_belong_to_the_same_stable_product",
      "tests/unit/test_project_engineering_baseline.py::test_baseline_does_not_load_or_validate_downstream_authority_bodies",
      "tests/unit/test_project_engineering_baseline.py::test_baseline_rejects_unsupported_contract",
      "tests/unit/test_project_engineering_baseline.py::test_baseline_schema_error_explains_type_in_chinese",
      "tests/unit/test_project_engineering_baseline.py::test_current_authority_must_bind_a_confirmed_revision",
      "tests/integration/test_configured_project_context.py::test_configuration_and_baseline_can_belong_to_different_repositories",
      "tests/integration/test_configured_project_context.py::test_cross_repository_adoption_requires_an_explicit_commit",
      "tests/integration/test_configured_project_context.py::test_existing_item_can_be_cancelled_when_the_current_locator_is_invalid",
      "tests/integration/test_configured_project_context.py::test_governance_profile_reuses_the_policy_repository_and_commit",
      "tests/integration/test_configured_project_context.py::test_multi_repository_execution_requires_an_existing_work_item_before_side_effects",
      "tests/integration/test_configured_project_context.py::test_public_project_status_reads_separated_authorities_without_creating_state",
      "tests/integration/test_configured_project_context.py::test_missing_authority_keeps_pinned_single_repository_metadata_read_only",
      "tests/integration/test_configured_project_context.py::test_split_authorities_use_one_context_and_exact_independent_commits",
      "tests/integration/test_configured_project_context.py::test_unadopted_status_does_not_create_the_configured_management_directory",
      "tests/unit/test_host_adapter.py::test_actual_result_accepts_a_planned_long_lived_move",
      "tests/unit/test_host_adapter.py::test_actual_result_accepts_a_removed_long_lived_artifact_only_after_unindexing",
      "tests/unit/test_host_adapter.py::test_actual_result_accepts_a_successor_alignment_over_an_unintegrated_baseline",
      "tests/unit/test_target_architecture_contract.py::test_every_mediated_relationship_has_both_declared_direct_legs",
      "tests/unit/test_target_architecture_contract.py::test_target_direct_dependency_graph_is_acyclic_and_default_denied",
      "tests/unit/test_target_architecture_contract.py::test_high_risk_boundaries_are_explicit_in_the_target_graph"
    ],
    "runs": {
      "d0856323c4b6": {
        "recorded_rows": 24,
        "outcome_counts": {
          "passed": 23,
          "failed": 1
        },
        "count_by_file": {
          "tests/unit/test_project_authority_consistency.py": 4,
          "tests/unit/test_project_engineering_baseline.py": 4,
          "tests/integration/test_configured_project_context.py": 10,
          "tests/unit/test_host_adapter.py": 3,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": [
          {
            "definition_id": "tests/unit/test_project_engineering_baseline.py::test_baseline_does_not_load_or_validate_downstream_authority_bodies",
            "path": "tests/unit/test_project_engineering_baseline.py",
            "node": "tests.unit.test_project_engineering_baseline::test_baseline_does_not_load_or_validate_downstream_authority_bodies",
            "outcome": "failed"
          }
        ]
      },
      "f5e20647248e": {
        "recorded_rows": 24,
        "outcome_counts": {
          "passed": 24
        },
        "count_by_file": {
          "tests/unit/test_project_authority_consistency.py": 4,
          "tests/unit/test_project_engineering_baseline.py": 4,
          "tests/integration/test_configured_project_context.py": 10,
          "tests/unit/test_host_adapter.py": 3,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      },
      "5bba08870241": {
        "recorded_rows": 4,
        "outcome_counts": {
          "passed": 4
        },
        "count_by_file": {
          "tests/unit/test_project_authority_consistency.py": 4
        },
        "non_passed": []
      },
      "7aaf327a1ccb": {
        "recorded_rows": 4,
        "outcome_counts": {
          "passed": 4
        },
        "count_by_file": {
          "tests/unit/test_project_engineering_baseline.py": 4
        },
        "non_passed": []
      },
      "30608175d9f5": {
        "recorded_rows": 2,
        "outcome_counts": {
          "passed": 2
        },
        "count_by_file": {
          "tests/integration/test_configured_project_context.py": 2
        },
        "non_passed": []
      }
    },
    "original_test_evidence": [
      {
        "claim": "All 4 tests pass confirming read-only baseline access for cross-authority checks",
        "kind": "test",
        "ref": "tests/unit/test_project_authority_consistency.py (4 tests)"
      },
      {
        "claim": "All 4 baseline tests pass confirming baseline validation and read behavior",
        "kind": "test",
        "ref": "tests/unit/test_project_engineering_baseline.py (4 tests)"
      }
    ]
  },
  {
    "target_id": "RELATION-E7B2B284E1684007",
    "definition_count": 19,
    "definition_count_by_file": {
      "tests/unit/test_git_project_reader.py": 4,
      "tests/unit/test_yaml_metadata_patch.py": 8,
      "tests/integration/test_local_git_lifecycle.py": 4,
      "tests/unit/test_target_architecture_contract.py": 3
    },
    "test_definition_ids": [
      "tests/unit/test_git_project_reader.py::test_git_for_windows_cmd_wrapper_resolves_to_direct_binary",
      "tests/unit/test_git_project_reader.py::test_read_only_reader_distinguishes_ancestor_from_descendant",
      "tests/unit/test_git_project_reader.py::test_worktree_paths_use_git_ignore_and_include_nonignored_untracked_files",
      "tests/unit/test_git_project_reader.py::test_unbound_directory_read_does_not_adopt_its_parent_repository",
      "tests/unit/test_yaml_metadata_patch.py::test_patch_yaml_values_changes_only_selected_metadata_spans",
      "tests/unit/test_yaml_metadata_patch.py::test_atomic_replacement_preserves_existing_file_mode",
      "tests/unit/test_yaml_metadata_patch.py::test_yaml_patch_transaction_recovers_after_one_file_was_already_written",
      "tests/unit/test_yaml_metadata_patch.py::test_yaml_patch_transaction_rolls_back_prior_files_when_later_write_fails",
      "tests/unit/test_yaml_metadata_patch.py::test_yaml_patch_transaction_rejects_case_aliases_of_one_target",
      "tests/unit/test_yaml_metadata_patch.py::test_yaml_patch_transaction_rejects_external_symlink",
      "tests/unit/test_yaml_metadata_patch.py::test_yaml_patch_transaction_rejects_internal_and_noncanonical_paths",
      "tests/unit/test_yaml_metadata_patch.py::test_yaml_patch_transaction_rejects_internal_symlink",
      "tests/integration/test_local_git_lifecycle.py::test_add_capability_records_public_interface_and_adr_through_full_lifecycle",
      "tests/integration/test_local_git_lifecycle.py::test_cancel_cleans_only_safe_empty_work_and_preserves_dirty_work",
      "tests/integration/test_local_git_lifecycle.py::test_complete_flow_tests_before_confirmation_then_commits_and_merges",
      "tests/integration/test_local_git_lifecycle.py::test_conflict_reverification_waits_for_the_agent_merge_commit",
      "tests/unit/test_target_architecture_contract.py::test_every_mediated_relationship_has_both_declared_direct_legs",
      "tests/unit/test_target_architecture_contract.py::test_target_direct_dependency_graph_is_acyclic_and_default_denied",
      "tests/unit/test_target_architecture_contract.py::test_high_risk_boundaries_are_explicit_in_the_target_graph"
    ],
    "runs": {
      "d0856323c4b6": {
        "recorded_rows": 24,
        "outcome_counts": {
          "passed": 22,
          "skipped": 2
        },
        "count_by_file": {
          "tests/unit/test_git_project_reader.py": 4,
          "tests/unit/test_yaml_metadata_patch.py": 13,
          "tests/integration/test_local_git_lifecycle.py": 4,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": [
          {
            "definition_id": "tests/unit/test_yaml_metadata_patch.py::test_yaml_patch_transaction_rejects_external_symlink",
            "path": "tests/unit/test_yaml_metadata_patch.py",
            "node": "tests.unit.test_yaml_metadata_patch::test_yaml_patch_transaction_rejects_external_symlink",
            "outcome": "skipped"
          },
          {
            "definition_id": "tests/unit/test_yaml_metadata_patch.py::test_yaml_patch_transaction_rejects_internal_symlink",
            "path": "tests/unit/test_yaml_metadata_patch.py",
            "node": "tests.unit.test_yaml_metadata_patch::test_yaml_patch_transaction_rejects_internal_symlink",
            "outcome": "skipped"
          }
        ]
      },
      "f5e20647248e": {
        "recorded_rows": 20,
        "outcome_counts": {
          "passed": 18,
          "skipped": 2
        },
        "count_by_file": {
          "tests/unit/test_git_project_reader.py": 4,
          "tests/unit/test_yaml_metadata_patch.py": 13,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": [
          {
            "definition_id": "tests/unit/test_yaml_metadata_patch.py::test_yaml_patch_transaction_rejects_external_symlink",
            "path": "tests/unit/test_yaml_metadata_patch.py",
            "node": "tests.unit.test_yaml_metadata_patch::test_yaml_patch_transaction_rejects_external_symlink",
            "outcome": "skipped"
          },
          {
            "definition_id": "tests/unit/test_yaml_metadata_patch.py::test_yaml_patch_transaction_rejects_internal_symlink",
            "path": "tests/unit/test_yaml_metadata_patch.py",
            "node": "tests.unit.test_yaml_metadata_patch::test_yaml_patch_transaction_rejects_internal_symlink",
            "outcome": "skipped"
          }
        ]
      }
    },
    "original_test_evidence": [
      {
        "claim": "Tests confirm selective metadata spans, atomic replacement, transaction recovery, rollback",
        "kind": "test",
        "ref": "tests/unit/test_yaml_metadata_patch.py (4+ tests)"
      },
      {
        "claim": "Tests confirm path resolution, ancestor/descendant distinction, worktree paths, unbound directory safety",
        "kind": "test",
        "ref": "tests/unit/test_git_project_reader.py (4 tests)"
      }
    ]
  },
  {
    "target_id": "RELATION-E908CF39D78845DF",
    "definition_count": 19,
    "definition_count_by_file": {
      "tests/unit/test_implementation_observation.py": 4,
      "tests/unit/test_composite_implementation_alignment.py": 2,
      "tests/unit/test_project_authority_contracts.py": 10,
      "tests/unit/test_target_architecture_contract.py": 3
    },
    "test_definition_ids": [
      "tests/unit/test_implementation_observation.py::test_external_provider_contract_is_valid_and_shipped_without_drift",
      "tests/unit/test_implementation_observation.py::test_content_snapshot_is_stable_when_unchanged_working_tree_is_committed",
      "tests/unit/test_implementation_observation.py::test_public_observation_seam_handles_six_language_ecosystems",
      "tests/unit/test_implementation_observation.py::test_observation_is_deterministic_for_the_same_working_tree",
      "tests/unit/test_composite_implementation_alignment.py::test_composite_alignment_distinguishes_equal_owned_paths_and_detects_backend_drift",
      "tests/unit/test_composite_implementation_alignment.py::test_source_repository_must_match_its_declared_scope",
      "tests/unit/test_project_authority_contracts.py::test_alignment_drift_scans_the_declared_project_package",
      "tests/unit/test_project_authority_contracts.py::test_alignment_runtime_rejects_empty_sources_claimed_as_complete",
      "tests/unit/test_project_authority_contracts.py::test_alignment_runtime_reports_exact_subordinate_field_errors",
      "tests/unit/test_project_authority_contracts.py::test_architecture_runtime_reads_and_validates_the_complete_target",
      "tests/unit/test_project_authority_contracts.py::test_architecture_runtime_rejects_an_unknown_contract",
      "tests/unit/test_project_authority_contracts.py::test_architecture_runtime_reports_exact_subordinate_field_errors",
      "tests/unit/test_project_authority_contracts.py::test_domain_runtime_reads_the_current_formal_authority",
      "tests/unit/test_project_authority_contracts.py::test_domain_runtime_rejects_an_unknown_contract",
      "tests/unit/test_project_authority_contracts.py::test_domain_runtime_routes_progressively_and_returns_typed_fact_closure",
      "tests/unit/test_project_authority_contracts.py::test_python_observation_rejects_a_src_container_instead_of_hiding_internal_edges",
      "tests/unit/test_target_architecture_contract.py::test_every_mediated_relationship_has_both_declared_direct_legs",
      "tests/unit/test_target_architecture_contract.py::test_target_direct_dependency_graph_is_acyclic_and_default_denied",
      "tests/unit/test_target_architecture_contract.py::test_high_risk_boundaries_are_explicit_in_the_target_graph"
    ],
    "runs": {
      "d0856323c4b6": {
        "recorded_rows": 19,
        "outcome_counts": {
          "passed": 19
        },
        "count_by_file": {
          "tests/unit/test_implementation_observation.py": 4,
          "tests/unit/test_composite_implementation_alignment.py": 2,
          "tests/unit/test_project_authority_contracts.py": 10,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      },
      "f5e20647248e": {
        "recorded_rows": 19,
        "outcome_counts": {
          "passed": 19
        },
        "count_by_file": {
          "tests/unit/test_implementation_observation.py": 4,
          "tests/unit/test_composite_implementation_alignment.py": 2,
          "tests/unit/test_project_authority_contracts.py": 10,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      },
      "5bba08870241": {
        "recorded_rows": 2,
        "outcome_counts": {
          "passed": 2
        },
        "count_by_file": {
          "tests/unit/test_composite_implementation_alignment.py": 2
        },
        "non_passed": []
      }
    },
    "original_test_evidence": [
      {
        "claim": "Tests confirm observation seam handles 6 language ecosystems and alignment checks are language-independent",
        "kind": "test",
        "ref": "tests/unit/test_implementation_observation.py (4 tests), tests/unit/test_composite_implementation_alignment.py (2 tests), tests/unit/test_project_authority_contracts.py (7 tests)"
      }
    ]
  },
  {
    "target_id": "RELATION-E98DCC2FA1624DB7",
    "definition_count": 26,
    "definition_count_by_file": {
      "tests/unit/test_git_project_reader.py": 4,
      "tests/unit/test_implementation_alignment_preparation.py": 3,
      "tests/unit/test_project_authority_decision.py": 4,
      "tests/unit/test_multi_repository_review_regressions.py": 5,
      "tests/unit/test_repository_evidence_boundaries.py": 6,
      "tests/unit/test_application_delivery_snapshots.py": 1,
      "tests/unit/test_target_architecture_contract.py": 3
    },
    "test_definition_ids": [
      "tests/unit/test_git_project_reader.py::test_git_for_windows_cmd_wrapper_resolves_to_direct_binary",
      "tests/unit/test_git_project_reader.py::test_read_only_reader_distinguishes_ancestor_from_descendant",
      "tests/unit/test_git_project_reader.py::test_worktree_paths_use_git_ignore_and_include_nonignored_untracked_files",
      "tests/unit/test_git_project_reader.py::test_unbound_directory_read_does_not_adopt_its_parent_repository",
      "tests/unit/test_implementation_alignment_preparation.py::test_single_module_and_root_sources_prepare_without_layout_changes",
      "tests/unit/test_implementation_alignment_preparation.py::test_binding_requires_one_current_alignment_operation",
      "tests/unit/test_implementation_alignment_preparation.py::test_preparation_store_is_content_addressed_without_mutable_pointer",
      "tests/unit/test_project_authority_decision.py::test_confirmation_checks_authority_before_creating_an_effect_lock",
      "tests/unit/test_project_authority_decision.py::test_owner_decision_binds_candidate_and_confirmed_content",
      "tests/unit/test_project_authority_decision.py::test_execution_reads_confirmed_unmerged_authority_from_its_exact_decision",
      "tests/unit/test_project_authority_decision.py::test_execution_does_not_use_authority_changed_after_owner_confirmation",
      "tests/unit/test_multi_repository_review_regressions.py::test_approved_continuation_keeps_preceding_slice_complete_in_both_views",
      "tests/unit/test_multi_repository_review_regressions.py::test_continuation_cannot_hide_other_changes_or_missing_completion",
      "tests/unit/test_multi_repository_review_regressions.py::test_continuation_exclusion_does_not_cover_equal_paths_in_another_repository",
      "tests/unit/test_multi_repository_review_regressions.py::test_final_refresh_still_requires_its_own_current_verification",
      "tests/unit/test_multi_repository_review_regressions.py::test_read_dependency_materializes_the_replanned_commit_after_prior_integration",
      "tests/unit/test_repository_evidence_boundaries.py::test_authority_confirmation_writes_only_the_qualified_body_and_separate_baseline",
      "tests/unit/test_repository_evidence_boundaries.py::test_later_slice_changes_do_not_invalidate_preceding_slice_inputs",
      "tests/unit/test_repository_evidence_boundaries.py::test_new_attempt_in_a_completed_repository_keeps_its_original_integration",
      "tests/unit/test_repository_evidence_boundaries.py::test_replan_cannot_drop_a_repository_with_unclosed_work",
      "tests/unit/test_repository_evidence_boundaries.py::test_result_references_use_the_planned_repository_even_with_equal_paths",
      "tests/unit/test_repository_evidence_boundaries.py::test_unbound_mechanical_paths_use_the_same_native_repository_only",
      "tests/unit/test_application_delivery_snapshots.py::test_actual_result_snapshot_rejects_an_added_unplanned_file",
      "tests/unit/test_target_architecture_contract.py::test_every_mediated_relationship_has_both_declared_direct_legs",
      "tests/unit/test_target_architecture_contract.py::test_target_direct_dependency_graph_is_acyclic_and_default_denied",
      "tests/unit/test_target_architecture_contract.py::test_high_risk_boundaries_are_explicit_in_the_target_graph"
    ],
    "runs": {
      "d0856323c4b6": {
        "recorded_rows": 32,
        "outcome_counts": {
          "passed": 32
        },
        "count_by_file": {
          "tests/unit/test_git_project_reader.py": 4,
          "tests/unit/test_implementation_alignment_preparation.py": 3,
          "tests/unit/test_project_authority_decision.py": 4,
          "tests/unit/test_multi_repository_review_regressions.py": 10,
          "tests/unit/test_repository_evidence_boundaries.py": 7,
          "tests/unit/test_application_delivery_snapshots.py": 1,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      },
      "f5e20647248e": {
        "recorded_rows": 32,
        "outcome_counts": {
          "passed": 32
        },
        "count_by_file": {
          "tests/unit/test_git_project_reader.py": 4,
          "tests/unit/test_implementation_alignment_preparation.py": 3,
          "tests/unit/test_project_authority_decision.py": 4,
          "tests/unit/test_multi_repository_review_regressions.py": 10,
          "tests/unit/test_repository_evidence_boundaries.py": 7,
          "tests/unit/test_application_delivery_snapshots.py": 1,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      },
      "5bba08870241": {
        "recorded_rows": 3,
        "outcome_counts": {
          "passed": 3
        },
        "count_by_file": {
          "tests/unit/test_implementation_alignment_preparation.py": 3
        },
        "non_passed": []
      }
    },
    "original_test_evidence": [
      {
        "claim": "Tests confirm read-only access, path identity, version binding",
        "kind": "test",
        "ref": "tests/unit/test_git_project_reader.py (4 tests), tests/unit/test_repository_evidence_boundaries.py (6 tests), tests/unit/test_multi_repository_review_regressions.py (5 tests)"
      }
    ]
  },
  {
    "target_id": "RELATION-F3A4968600194593",
    "definition_count": 19,
    "definition_count_by_file": {
      "tests/unit/test_project_authority_consistency.py": 4,
      "tests/integration/test_configured_project_context.py": 9,
      "tests/integration/test_local_git_lifecycle.py": 3,
      "tests/unit/test_target_architecture_contract.py": 3
    },
    "test_definition_ids": [
      "tests/unit/test_project_authority_consistency.py::test_immutable_full_authority_chain_uses_one_snapshot_and_bounded_batches",
      "tests/unit/test_project_authority_consistency.py::test_baseline_identity_must_match_the_loaded_authority",
      "tests/unit/test_project_authority_consistency.py::test_confirmed_policy_may_outlive_the_product_revision_it_was_reviewed_against",
      "tests/unit/test_project_authority_consistency.py::test_confirmed_policy_must_still_belong_to_the_same_stable_product",
      "tests/integration/test_configured_project_context.py::test_configuration_and_baseline_can_belong_to_different_repositories",
      "tests/integration/test_configured_project_context.py::test_cross_repository_adoption_requires_an_explicit_commit",
      "tests/integration/test_configured_project_context.py::test_existing_item_can_be_cancelled_when_the_current_locator_is_invalid",
      "tests/integration/test_configured_project_context.py::test_governance_profile_reuses_the_policy_repository_and_commit",
      "tests/integration/test_configured_project_context.py::test_multi_repository_execution_requires_an_existing_work_item_before_side_effects",
      "tests/integration/test_configured_project_context.py::test_public_project_status_reads_separated_authorities_without_creating_state",
      "tests/integration/test_configured_project_context.py::test_missing_authority_keeps_pinned_single_repository_metadata_read_only",
      "tests/integration/test_configured_project_context.py::test_split_authorities_use_one_context_and_exact_independent_commits",
      "tests/integration/test_configured_project_context.py::test_unadopted_status_does_not_create_the_configured_management_directory",
      "tests/integration/test_local_git_lifecycle.py::test_add_capability_records_public_interface_and_adr_through_full_lifecycle",
      "tests/integration/test_local_git_lifecycle.py::test_cancel_cleans_only_safe_empty_work_and_preserves_dirty_work",
      "tests/integration/test_local_git_lifecycle.py::test_complete_flow_tests_before_confirmation_then_commits_and_merges",
      "tests/unit/test_target_architecture_contract.py::test_every_mediated_relationship_has_both_declared_direct_legs",
      "tests/unit/test_target_architecture_contract.py::test_target_direct_dependency_graph_is_acyclic_and_default_denied",
      "tests/unit/test_target_architecture_contract.py::test_high_risk_boundaries_are_explicit_in_the_target_graph"
    ],
    "runs": {
      "d0856323c4b6": {
        "recorded_rows": 20,
        "outcome_counts": {
          "passed": 20
        },
        "count_by_file": {
          "tests/unit/test_project_authority_consistency.py": 4,
          "tests/integration/test_configured_project_context.py": 10,
          "tests/integration/test_local_git_lifecycle.py": 3,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      },
      "f5e20647248e": {
        "recorded_rows": 17,
        "outcome_counts": {
          "passed": 17
        },
        "count_by_file": {
          "tests/unit/test_project_authority_consistency.py": 4,
          "tests/integration/test_configured_project_context.py": 10,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      },
      "5bba08870241": {
        "recorded_rows": 4,
        "outcome_counts": {
          "passed": 4
        },
        "count_by_file": {
          "tests/unit/test_project_authority_consistency.py": 4
        },
        "non_passed": []
      },
      "30608175d9f5": {
        "recorded_rows": 2,
        "outcome_counts": {
          "passed": 2
        },
        "count_by_file": {
          "tests/integration/test_configured_project_context.py": 2
        },
        "non_passed": []
      }
    },
    "original_test_evidence": [
      {
        "claim": "Tests confirm authority chain reads from baseline-precise references",
        "kind": "test",
        "ref": "tests/unit/test_project_authority_consistency.py (4 tests)"
      },
      {
        "claim": "Tests confirm split authorities, configuration-baseline separation, baseline reads",
        "kind": "test",
        "ref": "tests/integration/test_configured_project_context.py (9 tests)"
      }
    ]
  },
  {
    "target_id": "RELATION-F81E17FC24D54C3E",
    "definition_count": 23,
    "definition_count_by_file": {
      "tests/unit/test_implementation_alignment_preparation.py": 3,
      "tests/unit/test_project_authority_decision.py": 13,
      "tests/unit/test_yaml_metadata_patch.py": 4,
      "tests/unit/test_target_architecture_contract.py": 3
    },
    "test_definition_ids": [
      "tests/unit/test_implementation_alignment_preparation.py::test_single_module_and_root_sources_prepare_without_layout_changes",
      "tests/unit/test_implementation_alignment_preparation.py::test_binding_requires_one_current_alignment_operation",
      "tests/unit/test_implementation_alignment_preparation.py::test_preparation_store_is_content_addressed_without_mutable_pointer",
      "tests/unit/test_project_authority_decision.py::test_confirmation_checks_authority_before_creating_an_effect_lock",
      "tests/unit/test_project_authority_decision.py::test_owner_decision_binds_candidate_and_confirmed_content",
      "tests/unit/test_project_authority_decision.py::test_execution_reads_confirmed_unmerged_authority_from_its_exact_decision",
      "tests/unit/test_project_authority_decision.py::test_execution_does_not_use_authority_changed_after_owner_confirmation",
      "tests/unit/test_yaml_metadata_patch.py::test_patch_yaml_values_changes_only_selected_metadata_spans",
      "tests/unit/test_yaml_metadata_patch.py::test_atomic_replacement_preserves_existing_file_mode",
      "tests/unit/test_yaml_metadata_patch.py::test_yaml_patch_transaction_recovers_after_one_file_was_already_written",
      "tests/unit/test_yaml_metadata_patch.py::test_yaml_patch_transaction_rolls_back_prior_files_when_later_write_fails",
      "tests/unit/test_project_authority_decision.py::test_authority_candidate_changes_when_confirmed_plan_changes",
      "tests/unit/test_project_authority_decision.py::test_authority_challenge_stays_bound_to_candidate_across_item_versions",
      "tests/unit/test_project_authority_decision.py::test_authority_confirmation_scope_requires_future_governance_candidates",
      "tests/unit/test_project_authority_decision.py::test_candidate_fingerprint_changes_when_only_yaml_comment_changes",
      "tests/unit/test_project_authority_decision.py::test_carried_forward_decision_revalidates_current_plan_change_targets",
      "tests/unit/test_project_authority_decision.py::test_confirmation_recovers_after_files_were_written_before_decision_record",
      "tests/unit/test_project_authority_decision.py::test_coordinator_restores_exact_bytes_when_decision_record_fails",
      "tests/unit/test_project_authority_decision.py::test_engineering_policy_candidate_binds_project_sources",
      "tests/unit/test_project_authority_decision.py::test_exact_owner_decision_is_carried_forward_after_safe_replanning",
      "tests/unit/test_target_architecture_contract.py::test_every_mediated_relationship_has_both_declared_direct_legs",
      "tests/unit/test_target_architecture_contract.py::test_target_direct_dependency_graph_is_acyclic_and_default_denied",
      "tests/unit/test_target_architecture_contract.py::test_high_risk_boundaries_are_explicit_in_the_target_graph"
    ],
    "runs": {
      "d0856323c4b6": {
        "recorded_rows": 23,
        "outcome_counts": {
          "passed": 23
        },
        "count_by_file": {
          "tests/unit/test_implementation_alignment_preparation.py": 3,
          "tests/unit/test_project_authority_decision.py": 13,
          "tests/unit/test_yaml_metadata_patch.py": 4,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      },
      "f5e20647248e": {
        "recorded_rows": 23,
        "outcome_counts": {
          "passed": 23
        },
        "count_by_file": {
          "tests/unit/test_implementation_alignment_preparation.py": 3,
          "tests/unit/test_project_authority_decision.py": 13,
          "tests/unit/test_yaml_metadata_patch.py": 4,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      },
      "5bba08870241": {
        "recorded_rows": 3,
        "outcome_counts": {
          "passed": 3
        },
        "count_by_file": {
          "tests/unit/test_implementation_alignment_preparation.py": 3
        },
        "non_passed": []
      }
    },
    "original_test_evidence": [
      {
        "claim": "Tests confirm authority-before-effect-lock, candidate binding, confirmed unmerged reads, post-confirmation invariance",
        "kind": "test",
        "ref": "tests/unit/test_project_authority_decision.py (7+ tests)"
      },
      {
        "claim": "Tests confirm selective span editing, atomic replacement, transaction recovery and rollback",
        "kind": "test",
        "ref": "tests/unit/test_yaml_metadata_patch.py (4 tests)"
      }
    ]
  },
  {
    "target_id": "RELATION-FC3CADC92F0245FC",
    "definition_count": 19,
    "definition_count_by_file": {
      "tests/unit/test_verification_runner.py": 4,
      "tests/unit/test_application_delivery_snapshots.py": 8,
      "tests/unit/test_host_adapter.py": 4,
      "tests/unit/test_target_architecture_contract.py": 3
    },
    "test_definition_ids": [
      "tests/unit/test_verification_runner.py::test_unclosed_process_cleanup_does_not_become_a_completed_blocked_receipt",
      "tests/unit/test_verification_runner.py::test_deduplicates_only_by_argv_cwd_and_run_kind",
      "tests/unit/test_verification_runner.py::test_verification_timeout_rejects_non_finite_numbers",
      "tests/unit/test_verification_runner.py::test_code_change_assessment_rejects_unknown_semantic_fields",
      "tests/unit/test_application_delivery_snapshots.py::test_actual_result_snapshot_rejects_an_added_unplanned_file",
      "tests/unit/test_application_delivery_snapshots.py::test_actual_result_snapshot_rejects_file_swap_before_commit",
      "tests/unit/test_application_delivery_snapshots.py::test_conflict_can_have_no_applicable_retest_command",
      "tests/unit/test_application_delivery_snapshots.py::test_immutable_result_commit_must_equal_the_presented_file_snapshot",
      "tests/unit/test_application_delivery_snapshots.py::test_prepared_in_place_merge_uses_the_target_tip_as_comparison_base",
      "tests/unit/test_application_delivery_snapshots.py::test_slice_completion_rejects_an_omitted_planned_file_operation",
      "tests/unit/test_application_delivery_snapshots.py::test_target_advance_projection_blocks_upstream_authority_pollution_only",
      "tests/unit/test_application_delivery_snapshots.py::test_terminal_failure_does_not_require_a_future_long_lived_artifact",
      "tests/unit/test_host_adapter.py::test_actual_result_accepts_a_planned_long_lived_move",
      "tests/unit/test_host_adapter.py::test_actual_result_accepts_a_removed_long_lived_artifact_only_after_unindexing",
      "tests/unit/test_host_adapter.py::test_actual_result_accepts_a_successor_alignment_over_an_unintegrated_baseline",
      "tests/unit/test_host_adapter.py::test_actual_result_does_not_skip_unplanned_domain_metadata_change",
      "tests/unit/test_target_architecture_contract.py::test_every_mediated_relationship_has_both_declared_direct_legs",
      "tests/unit/test_target_architecture_contract.py::test_target_direct_dependency_graph_is_acyclic_and_default_denied",
      "tests/unit/test_target_architecture_contract.py::test_high_risk_boundaries_are_explicit_in_the_target_graph"
    ],
    "runs": {
      "d0856323c4b6": {
        "recorded_rows": 21,
        "outcome_counts": {
          "passed": 21
        },
        "count_by_file": {
          "tests/unit/test_verification_runner.py": 6,
          "tests/unit/test_application_delivery_snapshots.py": 8,
          "tests/unit/test_host_adapter.py": 4,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      },
      "f5e20647248e": {
        "recorded_rows": 20,
        "outcome_counts": {
          "passed": 20
        },
        "count_by_file": {
          "tests/unit/test_verification_runner.py": 6,
          "tests/unit/test_application_delivery_snapshots.py": 8,
          "tests/unit/test_host_adapter.py": 3,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      },
      "30b2d951c8f4": {
        "recorded_rows": 6,
        "outcome_counts": {
          "passed": 6
        },
        "count_by_file": {
          "tests/unit/test_verification_runner.py": 6
        },
        "non_passed": []
      }
    },
    "original_test_evidence": [
      {
        "claim": "Tests confirm process cleanup, deduplication, timeout validation, code-change assessment field validation",
        "kind": "test",
        "ref": "tests/unit/test_verification_runner.py (4 tests)"
      },
      {
        "claim": "Tests confirm rejection of unplanned files, file swaps, omitted operations, upstream pollution blocking",
        "kind": "test",
        "ref": "tests/unit/test_application_delivery_snapshots.py (8 tests)"
      }
    ]
  },
  {
    "target_id": "RELATION-FC78A19148854EBE",
    "definition_count": 23,
    "definition_count_by_file": {
      "tests/unit/test_git_project_reader.py": 4,
      "tests/unit/test_project_engineering_policy.py": 4,
      "tests/unit/test_project_engineering_assurance.py": 8,
      "tests/integration/test_local_git_lifecycle.py": 4,
      "tests/unit/test_target_architecture_contract.py": 3
    },
    "test_definition_ids": [
      "tests/unit/test_git_project_reader.py::test_git_for_windows_cmd_wrapper_resolves_to_direct_binary",
      "tests/unit/test_git_project_reader.py::test_read_only_reader_distinguishes_ancestor_from_descendant",
      "tests/unit/test_git_project_reader.py::test_worktree_paths_use_git_ignore_and_include_nonignored_untracked_files",
      "tests/unit/test_git_project_reader.py::test_unbound_directory_read_does_not_adopt_its_parent_repository",
      "tests/unit/test_project_engineering_policy.py::test_repository_policy_is_the_current_independent_candidate",
      "tests/unit/test_project_engineering_policy.py::test_policy_profile_applies_method_adoption_and_owner_tailoring",
      "tests/unit/test_project_engineering_policy.py::test_policy_projects_only_deterministic_obligations_from_supplied_impacts",
      "tests/unit/test_project_engineering_policy.py::test_policy_rejects_unknown_method_and_weakened_strengthening",
      "tests/unit/test_project_engineering_assurance.py::test_assurance_matrix_keeps_internal_evidence_and_external_claims_apart",
      "tests/unit/test_project_engineering_assurance.py::test_assurance_rejects_a_satisfied_rule_without_evidence",
      "tests/unit/test_project_engineering_assurance.py::test_assurance_rejects_drifted_repository_evidence",
      "tests/unit/test_project_engineering_assurance.py::test_assurance_rejects_external_claim_without_external_receipt",
      "tests/unit/test_project_engineering_assurance.py::test_assurance_rejects_mixed_shared_reader_scopes",
      "tests/unit/test_project_engineering_assurance.py::test_bulk_evidence_failure_preserves_each_file_diagnostic",
      "tests/unit/test_project_engineering_assurance.py::test_duplicate_evidence_does_not_read_its_ignored_source",
      "tests/unit/test_project_engineering_assurance.py::test_read_model_exposes_assurance_as_a_separate_optional_projection",
      "tests/integration/test_local_git_lifecycle.py::test_add_capability_records_public_interface_and_adr_through_full_lifecycle",
      "tests/integration/test_local_git_lifecycle.py::test_cancel_cleans_only_safe_empty_work_and_preserves_dirty_work",
      "tests/integration/test_local_git_lifecycle.py::test_complete_flow_tests_before_confirmation_then_commits_and_merges",
      "tests/integration/test_local_git_lifecycle.py::test_conflict_reverification_waits_for_the_agent_merge_commit",
      "tests/unit/test_target_architecture_contract.py::test_every_mediated_relationship_has_both_declared_direct_legs",
      "tests/unit/test_target_architecture_contract.py::test_target_direct_dependency_graph_is_acyclic_and_default_denied",
      "tests/unit/test_target_architecture_contract.py::test_high_risk_boundaries_are_explicit_in_the_target_graph"
    ],
    "runs": {
      "d0856323c4b6": {
        "recorded_rows": 23,
        "outcome_counts": {
          "passed": 23
        },
        "count_by_file": {
          "tests/unit/test_git_project_reader.py": 4,
          "tests/unit/test_project_engineering_policy.py": 4,
          "tests/unit/test_project_engineering_assurance.py": 8,
          "tests/integration/test_local_git_lifecycle.py": 4,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      },
      "f5e20647248e": {
        "recorded_rows": 19,
        "outcome_counts": {
          "passed": 19
        },
        "count_by_file": {
          "tests/unit/test_git_project_reader.py": 4,
          "tests/unit/test_project_engineering_policy.py": 4,
          "tests/unit/test_project_engineering_assurance.py": 8,
          "tests/unit/test_target_architecture_contract.py": 3
        },
        "non_passed": []
      },
      "30b2d951c8f4": {
        "recorded_rows": 4,
        "outcome_counts": {
          "passed": 4
        },
        "count_by_file": {
          "tests/unit/test_project_engineering_policy.py": 4
        },
        "non_passed": []
      }
    },
    "original_test_evidence": [
      {
        "claim": "Tests confirm policy is the current independent candidate, profile adoption, deterministic obligations, method rejection",
        "kind": "test",
        "ref": "tests/unit/test_project_engineering_policy.py (4 tests)"
      },
      {
        "claim": "Tests confirm assurance matrix, evidence requirements, drifted repository evidence, external claims, scope mixing",
        "kind": "test",
        "ref": "tests/unit/test_project_engineering_assurance.py (8 tests)"
      }
    ]
  }
]
```
