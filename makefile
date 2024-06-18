.PHONY: run

run:
		NAMESPACE_CONNECTION_STR='local'  QUEUE_NAME='local' CONTENT_DIR=.'/exampleResource' CONTENT_URL='https://audio-content.bibleineverylanguage.org/content/'  python main.py --language_id en --resource_id ulb --exclude_format wav cue --dry_run    