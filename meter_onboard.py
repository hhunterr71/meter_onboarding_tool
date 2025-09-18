import main_script

def run_loop() -> None:
    while True:
        main_script.main()
        again = input("Run again? (y/n): ").strip().lower()
        if again != "y":
            print("Goodbye!")
            break

if __name__ == "__main__":
    run_loop()
