// Part II: build pipeline (Git + Pipeline + Docker Pipeline + Email Extension plugins)
pipeline {
    agent any

    options {
        timeout(time: 10, unit: 'MINUTES')
        disableConcurrentBuilds()
    }

    triggers {
        githubPush()
    }

    environment {
        COMPOSE  = 'docker compose -f docker-compose.jenkins.yml'
        APP_PORT = '8002'
    }

    stages {
        stage('Fetch code from GitHub') {
            steps {
                checkout scm
            }
        }

        stage('Build in Docker container') {
            steps {
                script {
                    // Docker Pipeline plugin: install deps and compile the app inside a clean Python container
                    docker.image('python:3.12-slim').inside('-e HOME=/tmp -e PIP_NO_CACHE_DIR=1') {
                        sh '''
                            python -m venv /tmp/venv
                            /tmp/venv/bin/pip install -q -r requirements.txt
                            /tmp/venv/bin/python -m compileall -q -x '(\\.venv|venv)' .
                        '''
                    }
                }
            }
        }

        stage('Prepare environment') {
            steps {
                withCredentials([file(credentialsId: 'f1fantasy-env', variable: 'ENV_FILE')]) {
                    sh 'cp "$ENV_FILE" .env && chmod 600 .env'
                }
            }
        }

        stage('Deploy with docker compose') {
            steps {
                sh '$COMPOSE down --remove-orphans || true'
                sh '$COMPOSE up -d'
            }
        }

        stage('Verify') {
            steps {
                sh '''
                    for i in $(seq 1 30); do
                        if curl -fsS "http://localhost:$APP_PORT/health"; then
                            echo ""; echo "App is up on port $APP_PORT"; exit 0
                        fi
                        sleep 5
                    done
                    echo "App did not become healthy"; $COMPOSE logs --tail 50; exit 1
                '''
            }
        }
    }

    post {
        always {
            script {
                // Email the person who made the push (author of the latest commit)
                def author = ''
                def name = ''
                try {
                    author = sh(script: "git log -1 --pretty=format:%ae", returnStdout: true).trim()
                    name   = sh(script: "git log -1 --pretty=format:%an", returnStdout: true).trim()
                } catch (e) {
                    echo "Could not read commit author: ${e}"
                }

                // Recipient = whoever authored the pushed commit.
                // Anything unknown or unresolvable goes to the repo owner, NEVER to the instructor by default.
                def OWNER_EMAIL       = 'zarocr7@gmail.com'
                def INSTRUCTOR_EMAIL  = 'qasimalik@gmail.com'
                def INSTRUCTOR_LOGINS = ['malik-qasim', 'qasimalik']

                def to = OWNER_EMAIL
                if (author && !author.contains('noreply.github.com')) {
                    to = author                                   // real address of the pusher
                } else if (author) {
                    // GitHub private address: 12345+login@users.noreply.github.com
                    def login = author.replaceAll(/^(\d+\+)?([^@]+)@.*$/, '$2').toLowerCase()
                    to = INSTRUCTOR_LOGINS.contains(login) ? INSTRUCTOR_EMAIL : OWNER_EMAIL
                }
                echo "Sending build result to: ${to}"

                emailext(
                    to: to,
                    recipientProviders: [requestor()],
                    subject: "Jenkins ${currentBuild.currentResult}: ${env.JOB_NAME} #${env.BUILD_NUMBER} (F1 Fantasy)",
                    mimeType: 'text/html',
                    attachLog: true,
                    body: """
                        <h2>F1 Fantasy build ${currentBuild.currentResult}</h2>
                        <p><b>Job:</b> ${env.JOB_NAME} #${env.BUILD_NUMBER}</p>
                        <p><b>Pushed by:</b> ${name} (${author})</p>
                        <p><b>Duration:</b> ${currentBuild.durationString}</p>
                        <p><b>App:</b> http://51.21.6.185:${env.APP_PORT}/</p>
                        <p><b>Build log:</b> <a href="${env.BUILD_URL}console">${env.BUILD_URL}console</a></p>
                        <p>Registration: FA23-BDS-039</p>
                    """
                )
            }
        }
    }
}
