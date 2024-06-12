from ai_state_machine.containers import init_genie_flow

if __name__ == '__main__':
    import argparse

    argparser = argparse.ArgumentParser(
        prog='genieflow',
        description="Utility to run API or Celery Worker for a Genie Flow program",
    )
    argparser.add_argument("command", required=True, help="sub command to run")
    argparser.add_argument("-c", "--config", required=True, help="path to config file")

    args = argparser.parse_args()

    genie_environment = init_genie_flow(args.config)

    match args.command:
        case "help":
            argparser.print_help()
            exit(0)
        case "api":

