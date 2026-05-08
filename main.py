import udmi_script
import site_model_editor
import building_batch
import yaml_batch_builder
import export_building_config
import building_config_updater
import onboard_config_updates

def show_menu() -> str:
    print("\n=== Meter Onboard Tool ===")
    print("\n-- one off tools --")
    print("  1. Translation Builder UDMI")
    print("     Build a UDMI translation for a single meter from a BACnet discovery JSON")
    print("  2. Single File Site Model Editor")
    print("     Normalize point names and fix units in a single metadata.json")
    print("\n-- batch tools --")
    print("  3. Batch Site Model Editor")
    print("     Normalize point names and fix units for all devices in a full site model")
    print("  4. Batch UDMI YAML Export")
    print("     Generate UDMI translation YAML files from an already-normalized site model")
    print("  5. Batch Building Config Sync   [runs 6 automatically]")
    print("     Export building configs from Carson and generate ADD/UPDATE YAMLs (files we need to onboard)")
    print("  6. Building Config Updater  (standalone)")
    print("     Generate ADD/UPDATE YAMLs for a project folder that already has building configs")
    print("  7. Onboard Updated Configs")
    print("     Submit ADD/UPDATE YAML files via stubby commands")
    while True:
        choice = input("\nSelect an option (1-7): ").strip()
        if choice in ("1", "2", "3", "4", "5", "6", "7"):
            return choice
        print("Invalid selection. Please enter 1-7.")

def run_loop() -> None:
    while True:
        choice = show_menu()
        if choice == "1":
            udmi_script.run_udmi()
        elif choice == "2":
            site_model_editor.run_site_model_editor()
        elif choice == "3":
            building_batch.run_building_batch()
        elif choice == "4":
            yaml_batch_builder.run_yaml_batch_builder()
        elif choice == "5":
            project_dir = export_building_config.run_export_batch()
            if project_dir:
                print("\nAutomatically running Building Config Updater on the same directory...")
                building_config_updater.run_building_config_updater(input_dir=project_dir)
        elif choice == "6":
            building_config_updater.run_building_config_updater()
        elif choice == "7":
            onboard_config_updates.run_onboard_updates()

        again = input("\nRun again? (y/n): ").strip().lower()
        if again != "y":
            print("Goodbye!")
            break

if __name__ == "__main__":
    run_loop()
