# 已复核评价的限定事实与引用纠正

原评价已有独立复核，但登记步骤拒绝了混入中文数量说明和多个文件的 ref，例如 `tests/unit/test_host_adapter.py 和 test_authority_cli_routing.py 12 个测试用例 run_id ...`。真实文件都在当前冻结包里；问题不应被解释为文件缺失。

本次只核对并修正可定位引用与统计口径，不重跑程序、测试或业务，不修改原记录。请保留原评价历史，重新提交同一 6 项的完整结构化候选供独立复核。

每个 evidence.ref 请使用一个实际冻结文件加精确行号/测试节点，或现有 packet 中对应目标 test_definition_ids 的明确定位。一个证据项不要把数量、运行说明、多个文件混进 ref；必要时拆成数项。数量与局限放 claim/limitations，不猜文件名或行号。

下方是程序从本轮相同 packet.test_definitions 的 recorded_executions 直接提取的事实。必须区分函数定义数、参数化后的 JUnit 行数、不同运行的 passed/skipped 和按文件分组数量。例如一致性目标是 12 个定义、在两次主要运行各 16 个测试行；维护目标的旧全量存在 3 个跳过，而快速运行有 21 个通过行。不要用混合口径得出所有运行全部通过，也不要把未独立保存的执行时源码摘要说成精确版本覆盖。

这些计数只证明所登记执行记录的直接数据，不证明实现或 Agent 语义。若事实更正影响原结论，由你按合同和证据重新判断；不预设 implemented。原独立通过不约束本次判断。所有冻结实现输入和合同未变化。

```json
[
  {
    "target_id": "CONSTRAINT-57F81F0ED3914049",
    "definition_count": 12,
    "definition_count_by_file": {
      "tests/unit/test_host_adapter.py": 11,
      "tests/unit/test_authority_cli_routing.py": 1
    },
    "test_definition_ids": [
      "tests/unit/test_host_adapter.py::test_cli_and_hosts_share_one_engineering_assessment_interface",
      "tests/unit/test_host_adapter.py::test_host_adapter_is_explicit_intent_transport_not_session_authority",
      "tests/unit/test_host_adapter.py::test_host_reads_project_governance_from_the_assessment_git_commit",
      "tests/unit/test_authority_cli_routing.py::test_authority_review_keeps_the_bundle_read_route",
      "tests/unit/test_host_adapter.py::test_actual_result_accepts_a_planned_long_lived_move",
      "tests/unit/test_host_adapter.py::test_actual_result_accepts_a_removed_long_lived_artifact_only_after_unindexing",
      "tests/unit/test_host_adapter.py::test_actual_result_accepts_a_successor_alignment_over_an_unintegrated_baseline",
      "tests/unit/test_host_adapter.py::test_actual_result_does_not_skip_unplanned_domain_metadata_change",
      "tests/unit/test_host_adapter.py::test_actual_result_rejects_an_unplanned_sibling_domain_fact_change",
      "tests/unit/test_host_adapter.py::test_actual_result_requires_every_planned_long_lived_artifact",
      "tests/unit/test_host_adapter.py::test_actual_result_translates_an_invalid_independent_architecture",
      "tests/unit/test_host_adapter.py::test_adopted_ddd_choice_reaches_plan_actual_result_and_focused_read_model"
    ],
    "runs": {
      "d0856323c4b6": {
        "recorded_rows": 12,
        "outcome_counts": {
          "passed": 12
        },
        "count_by_file": {
          "tests/unit/test_host_adapter.py": 11,
          "tests/unit/test_authority_cli_routing.py": 1
        },
        "non_passed": []
      },
      "f5e20647248e": {
        "recorded_rows": 9,
        "outcome_counts": {
          "passed": 9
        },
        "count_by_file": {
          "tests/unit/test_host_adapter.py": 8,
          "tests/unit/test_authority_cli_routing.py": 1
        },
        "non_passed": []
      }
    },
    "original_test_evidence": [
      {
        "claim": "全部 12 个相关测试在记录执行中均 passed，source_at_execution_hash 未独立捕获",
        "kind": "test",
        "ref": "tests/unit/test_host_adapter.py 和 test_authority_cli_routing.py 12 个测试用例 run_id d0856323c4b6 / f5e20647248e"
      }
    ]
  },
  {
    "target_id": "CONSTRAINT-58B9D32F32AD4661",
    "definition_count": 10,
    "definition_count_by_file": {
      "tests/unit/test_target_architecture_contract.py": 10
    },
    "test_definition_ids": [
      "tests/unit/test_target_architecture_contract.py::test_architecture_contract_rejects_current_implementation_paths",
      "tests/unit/test_target_architecture_contract.py::test_target_architecture_contains_no_current_paths_or_evidence_fields",
      "tests/unit/test_target_architecture_contract.py::test_architecture_cannot_be_confirmable_before_domain_confirmation",
      "tests/unit/test_target_architecture_contract.py::test_architecture_stages_are_ordered_and_cover_every_target_module",
      "tests/unit/test_target_architecture_contract.py::test_every_active_domain_fact_has_one_nonempty_architecture_disposition",
      "tests/unit/test_target_architecture_contract.py::test_every_mediated_relationship_has_both_declared_direct_legs",
      "tests/unit/test_target_architecture_contract.py::test_high_risk_boundaries_are_explicit_in_the_target_graph",
      "tests/unit/test_target_architecture_contract.py::test_repository_architecture_artifacts_match_the_contract",
      "tests/unit/test_target_architecture_contract.py::test_target_direct_dependency_graph_is_acyclic_and_default_denied",
      "tests/unit/test_target_architecture_contract.py::test_target_modules_have_unique_stable_interfaces_and_closed_references"
    ],
    "runs": {
      "d0856323c4b6": {
        "recorded_rows": 10,
        "outcome_counts": {
          "passed": 10
        },
        "count_by_file": {
          "tests/unit/test_target_architecture_contract.py": 10
        },
        "non_passed": []
      },
      "f5e20647248e": {
        "recorded_rows": 10,
        "outcome_counts": {
          "passed": 10
        },
        "count_by_file": {
          "tests/unit/test_target_architecture_contract.py": 10
        },
        "non_passed": []
      }
    },
    "original_test_evidence": [
      {
        "claim": "全部 10 个相关测试在两次记录执行中均 passed",
        "kind": "test",
        "ref": "tests/unit/test_target_architecture_contract.py 10 个测试 run_id d0856323c4b6 / f5e20647248e"
      }
    ]
  },
  {
    "target_id": "CONSTRAINT-610485D3758B4216",
    "definition_count": 12,
    "definition_count_by_file": {
      "tests/unit/test_implementation_observation.py": 12
    },
    "test_definition_ids": [
      "tests/unit/test_implementation_observation.py::test_authorized_external_provider_extends_language_support",
      "tests/unit/test_implementation_observation.py::test_dynamic_or_unresolved_relationships_remain_visible",
      "tests/unit/test_implementation_observation.py::test_external_provider_contract_is_valid_and_shipped_without_drift",
      "tests/unit/test_implementation_observation.py::test_external_provider_failures_never_become_empty_success",
      "tests/unit/test_implementation_observation.py::test_external_provider_is_not_run_after_a_confirmed_material_changes",
      "tests/unit/test_implementation_observation.py::test_external_provider_is_not_run_without_call_authorization",
      "tests/unit/test_implementation_observation.py::test_external_provider_node_keys_distinguish_logical_nodes_on_one_path",
      "tests/unit/test_implementation_observation.py::test_external_provider_output_must_cover_exact_declared_sources",
      "tests/unit/test_implementation_observation.py::test_external_provider_request_limit_is_a_typed_failed_observation",
      "tests/unit/test_implementation_observation.py::test_go_observation_resolves_multiple_modules_and_local_replace",
      "tests/unit/test_implementation_observation.py::test_invalid_scope_is_rejected_before_any_observation",
      "tests/unit/test_implementation_observation.py::test_observation_is_deterministic_for_the_same_working_tree"
    ],
    "runs": {
      "d0856323c4b6": {
        "recorded_rows": 14,
        "outcome_counts": {
          "passed": 14
        },
        "count_by_file": {
          "tests/unit/test_implementation_observation.py": 14
        },
        "non_passed": []
      },
      "f5e20647248e": {
        "recorded_rows": 14,
        "outcome_counts": {
          "passed": 14
        },
        "count_by_file": {
          "tests/unit/test_implementation_observation.py": 14
        },
        "non_passed": []
      }
    },
    "original_test_evidence": [
      {
        "claim": "全部 12 个相关测试在记录执行中均 passed",
        "kind": "test",
        "ref": "tests/unit/test_implementation_observation.py 12 个测试 run_id d0856323c4b6 / f5e20647248e"
      }
    ]
  },
  {
    "target_id": "CONSTRAINT-6CDB801E1CD24D15",
    "definition_count": 12,
    "definition_count_by_file": {
      "tests/unit/test_application_delivery_snapshots.py": 6,
      "tests/unit/test_host_adapter.py": 5,
      "tests/unit/test_verification_runner.py": 1
    },
    "test_definition_ids": [
      "tests/unit/test_application_delivery_snapshots.py::test_actual_result_snapshot_rejects_an_added_unplanned_file",
      "tests/unit/test_application_delivery_snapshots.py::test_actual_result_snapshot_rejects_file_swap_before_commit",
      "tests/unit/test_application_delivery_snapshots.py::test_conflict_can_have_no_applicable_retest_command",
      "tests/unit/test_application_delivery_snapshots.py::test_immutable_result_commit_must_equal_the_presented_file_snapshot",
      "tests/unit/test_application_delivery_snapshots.py::test_slice_completion_rejects_an_omitted_planned_file_operation",
      "tests/unit/test_application_delivery_snapshots.py::test_terminal_failure_does_not_require_a_future_long_lived_artifact",
      "tests/unit/test_host_adapter.py::test_verification_action_discloses_exact_confirmed_command_record",
      "tests/unit/test_host_adapter.py::test_verification_blocks_paths_owned_only_by_a_future_slice",
      "tests/unit/test_host_adapter.py::test_verification_cannot_skip_the_current_implementation_slice",
      "tests/unit/test_host_adapter.py::test_verification_reports_unplanned_command_byproducts_separately",
      "tests/unit/test_host_adapter.py::test_zero_command_slice_completion_still_rejects_future_slice_paths",
      "tests/unit/test_verification_runner.py::test_no_planned_command_is_not_required_instead_of_failed"
    ],
    "runs": {
      "d0856323c4b6": {
        "recorded_rows": 12,
        "outcome_counts": {
          "passed": 12
        },
        "count_by_file": {
          "tests/unit/test_application_delivery_snapshots.py": 6,
          "tests/unit/test_host_adapter.py": 5,
          "tests/unit/test_verification_runner.py": 1
        },
        "non_passed": []
      },
      "f5e20647248e": {
        "recorded_rows": 12,
        "outcome_counts": {
          "passed": 12
        },
        "count_by_file": {
          "tests/unit/test_application_delivery_snapshots.py": 6,
          "tests/unit/test_host_adapter.py": 5,
          "tests/unit/test_verification_runner.py": 1
        },
        "non_passed": []
      },
      "30b2d951c8f4": {
        "recorded_rows": 1,
        "outcome_counts": {
          "passed": 1
        },
        "count_by_file": {
          "tests/unit/test_verification_runner.py": 1
        },
        "non_passed": []
      }
    },
    "original_test_evidence": [
      {
        "claim": "全部 12 个相关测试在记录执行中均 passed",
        "kind": "test",
        "ref": "tests/unit/test_application_delivery_snapshots.py 6个 + tests/unit/test_host_adapter.py 5个 + tests/unit/test_verification_runner.py::test_no_planned_command_is_not_required_instead_of_failed"
      }
    ]
  },
  {
    "target_id": "CONSTRAINT-6DFE7F10B9154809",
    "definition_count": 12,
    "definition_count_by_file": {
      "tests/unit/test_project_authority_consistency.py": 10,
      "tests/unit/test_pending_authority_candidates.py": 2
    },
    "test_definition_ids": [
      "tests/unit/test_project_authority_consistency.py::test_actual_result_cannot_adopt_an_independent_product_revision",
      "tests/unit/test_project_authority_consistency.py::test_actual_result_confirmation_snapshot_detects_authority_body_swap",
      "tests/unit/test_project_authority_consistency.py::test_baseline_identity_must_match_the_loaded_authority",
      "tests/unit/test_project_authority_consistency.py::test_confirmed_policy_may_outlive_the_product_revision_it_was_reviewed_against",
      "tests/unit/test_project_authority_consistency.py::test_domain_source_change_invalidates_only_known_downstream_chain",
      "tests/unit/test_project_authority_consistency.py::test_engineering_governance_context_hides_authority_implementations",
      "tests/unit/test_project_authority_consistency.py::test_first_project_candidate_reports_every_authority_as_new",
      "tests/unit/test_project_authority_consistency.py::test_immutable_full_authority_chain_uses_one_snapshot_and_bounded_batches",
      "tests/unit/test_project_authority_consistency.py::test_integrated_commit_must_still_match_the_accepted_authority_snapshot",
      "tests/unit/test_project_authority_consistency.py::test_working_tree_candidate_baseline_can_point_at_a_draft_revision",
      "tests/unit/test_pending_authority_candidates.py::test_explicit_candidate_read_keeps_pending_successor_separate_from_adoption",
      "tests/unit/test_pending_authority_candidates.py::test_pending_status_does_not_waive_exact_successor_binding"
    ],
    "runs": {
      "d0856323c4b6": {
        "recorded_rows": 16,
        "outcome_counts": {
          "passed": 16
        },
        "count_by_file": {
          "tests/unit/test_project_authority_consistency.py": 10,
          "tests/unit/test_pending_authority_candidates.py": 6
        },
        "non_passed": []
      },
      "f5e20647248e": {
        "recorded_rows": 16,
        "outcome_counts": {
          "passed": 16
        },
        "count_by_file": {
          "tests/unit/test_project_authority_consistency.py": 10,
          "tests/unit/test_pending_authority_candidates.py": 6
        },
        "non_passed": []
      },
      "5bba08870241": {
        "recorded_rows": 10,
        "outcome_counts": {
          "passed": 10
        },
        "count_by_file": {
          "tests/unit/test_project_authority_consistency.py": 10
        },
        "non_passed": []
      }
    },
    "original_test_evidence": [
      {
        "claim": "全部 14 个相关测试在记录执行中均 passed",
        "kind": "test",
        "ref": "tests/unit/test_project_authority_consistency.py 12个 + tests/unit/test_pending_authority_candidates.py 2个"
      }
    ]
  },
  {
    "target_id": "CONSTRAINT-0F36EFE1A9DC481A",
    "definition_count": 15,
    "definition_count_by_file": {
      "tests/unit/test_runtime_format_admission.py": 1,
      "tests/unit/test_runtime_upgrade.py": 8,
      "tests/integration/test_upgrade_cli.py": 2,
      "tests/unit/test_delivery_activity.py": 1,
      "tests/unit/test_workflow_authority.py": 1,
      "tests/unit/test_managed_installation.py": 2
    },
    "test_definition_ids": [
      "tests/unit/test_runtime_format_admission.py::test_precheck_rejects_noncanonical_format_without_changing_project_content",
      "tests/unit/test_runtime_upgrade.py::test_runtime_maintenance_preserves_original_records_and_current_format",
      "tests/unit/test_runtime_upgrade.py::test_completed_inflight_write_invalidates_plan_without_stranding_maintenance",
      "tests/unit/test_runtime_upgrade.py::test_fence_only_recovery_preserves_a_late_activity_change",
      "tests/unit/test_runtime_upgrade.py::test_initial_upgrade_journal_cannot_follow_a_directory_junction",
      "tests/unit/test_runtime_upgrade.py::test_recovery_finishes_after_restoring_runtime_selection_then_crashing",
      "tests/unit/test_runtime_upgrade.py::test_restore_preserves_new_facts_and_only_restores_an_unchanged_generation",
      "tests/unit/test_runtime_upgrade.py::test_restore_refuses_a_new_activity_database_created_after_upgrade",
      "tests/unit/test_runtime_upgrade.py::test_runtime_maintenance_preserves_records_and_reports_missing_logs",
      "tests/integration/test_upgrade_cli.py::test_native_entry_reads_switched_history_inside_maintenance_without_writing",
      "tests/integration/test_upgrade_cli.py::test_public_upgrade_precheck_apply_status_and_history",
      "tests/unit/test_delivery_activity.py::test_future_activity_format_is_rejected_without_repair",
      "tests/unit/test_workflow_authority.py::test_authority_owns_one_current_state_and_one_event_history",
      "tests/unit/test_managed_installation.py::test_actual_interpreter_probe_uses_the_same_package_and_skill_identity_protocol",
      "tests/unit/test_managed_installation.py::test_combined_precheck_binds_the_target_and_source_without_creating_an_installation"
    ],
    "runs": {
      "7aaf327a1ccb": {
        "recorded_rows": 18,
        "outcome_counts": {
          "passed": 15,
          "skipped": 3
        },
        "count_by_file": {
          "tests/unit/test_runtime_format_admission.py": 6,
          "tests/unit/test_runtime_upgrade.py": 8,
          "tests/integration/test_upgrade_cli.py": 2,
          "tests/unit/test_managed_installation.py": 2
        },
        "non_passed": [
          {
            "definition_id": "tests/integration/test_upgrade_cli.py::test_native_entry_reads_switched_history_inside_maintenance_without_writing",
            "path": "tests/integration/test_upgrade_cli.py",
            "node": "tests.integration.test_upgrade_cli::test_native_entry_reads_switched_history_inside_maintenance_without_writing",
            "outcome": "skipped"
          },
          {
            "definition_id": "tests/unit/test_managed_installation.py::test_actual_interpreter_probe_uses_the_same_package_and_skill_identity_protocol",
            "path": "tests/unit/test_managed_installation.py",
            "node": "tests.unit.test_managed_installation::test_actual_interpreter_probe_uses_the_same_package_and_skill_identity_protocol",
            "outcome": "skipped"
          },
          {
            "definition_id": "tests/unit/test_managed_installation.py::test_combined_precheck_binds_the_target_and_source_without_creating_an_installation",
            "path": "tests/unit/test_managed_installation.py",
            "node": "tests.unit.test_managed_installation::test_combined_precheck_binds_the_target_and_source_without_creating_an_installation",
            "outcome": "skipped"
          }
        ]
      },
      "f5e20647248e": {
        "recorded_rows": 21,
        "outcome_counts": {
          "passed": 21
        },
        "count_by_file": {
          "tests/unit/test_runtime_format_admission.py": 6,
          "tests/unit/test_runtime_upgrade.py": 8,
          "tests/integration/test_upgrade_cli.py": 2,
          "tests/unit/test_delivery_activity.py": 2,
          "tests/unit/test_workflow_authority.py": 1,
          "tests/unit/test_managed_installation.py": 2
        },
        "non_passed": []
      },
      "d0856323c4b6": {
        "recorded_rows": 15,
        "outcome_counts": {
          "passed": 12,
          "skipped": 3
        },
        "count_by_file": {
          "tests/unit/test_runtime_upgrade.py": 8,
          "tests/integration/test_upgrade_cli.py": 2,
          "tests/unit/test_delivery_activity.py": 2,
          "tests/unit/test_workflow_authority.py": 1,
          "tests/unit/test_managed_installation.py": 2
        },
        "non_passed": [
          {
            "definition_id": "tests/integration/test_upgrade_cli.py::test_native_entry_reads_switched_history_inside_maintenance_without_writing",
            "path": "tests/integration/test_upgrade_cli.py",
            "node": "tests.integration.test_upgrade_cli::test_native_entry_reads_switched_history_inside_maintenance_without_writing",
            "outcome": "skipped"
          },
          {
            "definition_id": "tests/unit/test_managed_installation.py::test_actual_interpreter_probe_uses_the_same_package_and_skill_identity_protocol",
            "path": "tests/unit/test_managed_installation.py",
            "node": "tests.unit.test_managed_installation::test_actual_interpreter_probe_uses_the_same_package_and_skill_identity_protocol",
            "outcome": "skipped"
          },
          {
            "definition_id": "tests/unit/test_managed_installation.py::test_combined_precheck_binds_the_target_and_source_without_creating_an_installation",
            "path": "tests/unit/test_managed_installation.py",
            "node": "tests.unit.test_managed_installation::test_combined_precheck_binds_the_target_and_source_without_creating_an_installation",
            "outcome": "skipped"
          }
        ]
      },
      "c1dfd12d2187": {
        "recorded_rows": 4,
        "outcome_counts": {
          "passed": 4
        },
        "count_by_file": {
          "tests/integration/test_upgrade_cli.py": 2,
          "tests/unit/test_managed_installation.py": 2
        },
        "non_passed": []
      },
      "30608175d9f5": {
        "recorded_rows": 2,
        "outcome_counts": {
          "passed": 2
        },
        "count_by_file": {
          "tests/unit/test_delivery_activity.py": 2
        },
        "non_passed": []
      }
    },
    "original_test_evidence": [
      {
        "claim": "全部 15 个相关测试在记录执行中均 passed",
        "kind": "test",
        "ref": "tests/unit/test_runtime_upgrade.py 9个 + tests/integration/test_upgrade_cli.py 2个 + test_runtime_format_admission.py + test_delivery_activity.py + test_workflow_authority.py + test_managed_installation.py 各 1个"
      }
    ]
  }
]
```
