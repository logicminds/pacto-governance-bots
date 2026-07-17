import sys

if __name__ == "__main__":
    if "--version" in sys.argv:
        from bosun.version import full_version

        print(full_version())
        sys.exit(0)

    from bosun.bosun import main

    main()
